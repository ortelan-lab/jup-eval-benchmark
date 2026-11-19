"""Recompute the November table from published ratings. No network required."""
import csv
import json
from collections import defaultdict
from math import isclose
from pathlib import Path
from statistics import fmean
from paired_interval import bootstrap

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_trials(config):
    trials = defaultdict(dict)
    with (ROOT / 'data/trial-scores.csv').open() as handle:
        for row in csv.DictReader(handle):
            system = row['system']
            key = row['case_id'], int(row['trial'])
            points = float(row['points'])
            require(key not in trials[system], f'Duplicate trial {system} {key}')
            weights = config['criterion_weights']
            ratings = {criterion: int(row[criterion]) for criterion in weights}
            require(all(v in range(5) for v in ratings.values()), f'Invalid rating {key}')
            flags = [row['critical'], row['forbidden_attempt']]
            require(all(flag in ('0','1') for flag in flags), f'Invalid flag {key}')
            zero = row['status'] != 'completed' or '1' in flags
            expected = 0 if zero else 25 * sum(weights[c] * ratings[c] for c in weights)
            require(isclose(expected, points, abs_tol=1e-9), f'Trial score mismatch {system} {key}')
            trials[system][key] = points
    return trials


def main():
    cases = json.loads((ROOT / 'data/scenarios.json').read_text())
    config = json.loads((ROOT / 'compass/config.json').read_text())
    results = json.loads((ROOT / 'data/results.json').read_text())
    trials = load_trials(config)
    expected = {(c['id'], trial) for c in cases for trial in (1, 2, 3)}
    require(set(trials) == {r['system'] for r in results}, 'System coverage mismatch')
    for result in results:
        name = result['system']
        scores = trials[name]
        require(set(scores) == expected, f'Trial coverage mismatch for {name}')
        families = defaultdict(lambda: defaultdict(list))
        for case in cases:
            case_mean = fmean(scores[case['id'], i] for i in (1, 2, 3))
            families[case['dimension']][case['family_id']].append(case_mean)
        dimensions = {d: fmean(fmean(group) for group in groups.values()) for d, groups in families.items()}
        for d, value in dimensions.items():
            require(isclose(value, result['dimensions'][d], abs_tol=1e-9), f'Dimension mismatch {name} {d}')
        total = sum(w * dimensions[d] for d, w in config['dimension_weights'].items())
        require(isclose(total, result['composite'], abs_tol=1e-9), f'Composite mismatch {name}')
        values = {d: [fmean(f[fid]) for fid in sorted(f)] for d, f in families.items()}
        _, low, high = bootstrap(values, config)
        require(all(isclose(a,b,abs_tol=1e-9) for a,b in zip((low,high),result['interval'])), f'Interval mismatch {name}')
        print(f'{name}: {total:.2f} ({len(scores)} verified trial scores)')


if __name__ == '__main__':
    main()
