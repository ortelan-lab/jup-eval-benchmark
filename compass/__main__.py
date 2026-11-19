"""Public command line for Judgment Under Pressure Evaluation."""
import argparse
import json
import os
from pathlib import Path
from statistics import mean

from .core import canonical_hash, load, require, validate, validate_grade, validate_plan
from .corrections import corrected_score
from .judge import judge_runs
from .runner import LiveAdapter, MockAdapter, make_plan, run_plan


class ChatEndpoint(LiveAdapter):
    def request(self, messages, tools):
        body, headers = super().request(messages, tools)
        if self.options.get('provider_default_temperature'):
            body.pop('temperature', None)
        if self.options.get('token_field') == 'max_completion_tokens':
            body['max_completion_tokens'] = body.pop('max_tokens')
        return body, headers


class JsonGrader(LiveAdapter):
    def request(self, messages, tools):
        body, headers = super().request(messages, tools)
        body['response_format'] = {'type': 'json_object'}
        return body, headers


def records(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def save(path, value):
    with Path(path).open('x') as out:
        json.dump(value, out, indent=2, allow_nan=False)
        out.write('\n')


def score(plan, responses, grades, cfg, cases):
    validate_plan(plan, cfg, cases)
    index = {case['id']: case for case in cases}
    expected = {(cid, repeat) for cid in plan['case_ids'] for repeat in range(plan['repeats'])}
    ratings = {(g['case_id'], g['repeat']): g for g in grades}
    slots = {(r['case_id'], r['repeat']) for r in responses}
    require(slots == set(ratings) == expected and len(responses) == len(grades) == len(slots), 'Incomplete or duplicate trials')
    families = {dim: {} for dim in cfg['dimension_weights']}
    digest = canonical_hash(plan)
    for r in responses:
        require(not r.get('synthetic'), 'Offline fixture is ineligible for scoring')
        require(r['run_id'] == plan['run_id'] and r['plan_sha256'] == digest, 'Wrong plan')
        c = index[r['case_id']]
        g = ratings[r['case_id'], r['repeat']]
        validate_grade(g, r, cfg, statuses=('provisional','final'))
        families[c['dimension']].setdefault(c['family_id'], []).append(corrected_score(g, r, c, cfg))
    dims = {d: mean(mean(v) for v in groups.values()) for d, groups in families.items() if groups}
    total = sum(dims[k] * w for k,w in cfg['dimension_weights'].items()) if len(dims)==len(families) else None
    return dict(split=plan['split'], cases=len(plan['case_ids']), trials=len(slots), dimensions=dims, composite=total,
                full_round=plan['split']=='all' and plan['repeats']==3, plan_sha256=digest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='operation', required=True)
    commands.add_parser('validate')
    plan = commands.add_parser('plan')
    plan.add_argument('--model', required=True)
    plan.add_argument('--split', choices=('all','smoke','development','candidate_holdout','challenge'), default='all')
    plan.add_argument('--repeats', type=int, default=3)
    for cmd in ('run','judge','score'):
        sub = commands.add_parser(cmd)
        sub.add_argument('--plan', required=True)
        if cmd in ('judge','score'):
            sub.add_argument('--responses', required=True)
        if cmd == 'score':
            sub.add_argument('--grades', required=True)
        else:
            sub.add_argument('--live', action='store_true')
            sub.add_argument('--base-url', help='HTTPS OpenAI-compatible base URL ending in /v1')
            sub.add_argument('--input-rate', type=float, help='USD per million input tokens')
            sub.add_argument('--output-rate', type=float, help='USD per million output tokens')
            sub.add_argument('--cap', type=float, help='Local USD ceiling for this command')
            sub.add_argument('--key-env', default='JUP_API_KEY')
            if cmd == 'judge':
                sub.add_argument('--model',required=True)
        sub.add_argument('--out', required=True)
    plan.add_argument('--out',required=True)
    plan.add_argument('--provider-default-temperature', action='store_true')
    plan.add_argument('--token-field', choices=('max_tokens','max_completion_tokens'), default='max_tokens')
    args = parser.parse_args()
    cfg, cases = load()
    validate(cfg, cases)
    if args.operation == 'validate':
        print(f'{len(cases)} cases, {len(set(c["family_id"] for c in cases))} families; bank SHA-256 {canonical_hash(cases)}')
        return
    if args.operation == 'plan':
        frozen = make_plan(cfg, cases, args.model, split=args.split, repeats=args.repeats)
        frozen['endpoint_options'] = dict(provider_default_temperature=args.provider_default_temperature, token_field=args.token_field)
        save(args.out, frozen)
        return
    frozen = json.loads(Path(args.plan).read_text())
    validate_plan(frozen, cfg, cases)
    if args.operation == 'score':
        result=score(frozen,records(args.responses),records(args.grades),cfg,cases)
        save(args.out,result)
        print(json.dumps(result,indent=2))
        return
    if args.operation == 'judge' and not args.live:
        parser.error('Grading requires --live and your selected evaluator credentials')
    adapter = MockAdapter()
    if args.live:
        if not (args.base_url and os.environ.get(args.key_env) and args.cap and args.input_rate and args.output_rate):
            parser.error('Live calls require a base URL, key environment variable, input/output rates and cap')
        model = args.model if args.operation=='judge' else frozen['model']
        adapter_type = JsonGrader if args.operation == 'judge' else ChatEndpoint
        adapter = adapter_type(args.base_url, args.key_env, model, args.input_rate, args.output_rate, args.cap, dict(cfg, max_output_tokens=3000) if args.operation=='judge' else cfg)
        if args.operation == 'run':
            adapter.options = frozen.get('endpoint_options', {})
            adapter.provenance.update(adapter.options)
    if args.operation=='judge':
        runs=records(args.responses)
        require(bool(runs) and all(not r.get('synthetic') and r['plan_sha256']==canonical_hash(frozen) for r in runs), 'Expected real answers from the selected plan')
        status = judge_runs(runs, cases, cfg, adapter, args.out)
        print(json.dumps(status))
        if status['graded'] != status['expected'] or status['failures']:
            raise SystemExit(2)
    else:
        status=run_plan(frozen,cfg,cases,adapter,args.out,synthetic=not args.live)
        print(status)
        if status!='finished':raise SystemExit(2)


if __name__=='__main__':
    main()
