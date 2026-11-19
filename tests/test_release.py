import unittest
from collections import Counter

from compass.core import canonical_hash, load, validate, validate_plan
from compass.corrections import corrected_score
from compass.judge import judge_payload
from compass.runner import make_plan


class ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config, cls.cases = load()

    def test_full_plan_covers_every_case_three_times(self):
        validate(self.config, self.cases)
        plan = make_plan(self.config, self.cases, 'example', split='all')
        validate_plan(plan, self.config, self.cases)
        self.assertEqual(468, len(plan['case_ids']) * plan['repeats'])
        self.assertEqual(156, len(set(plan['case_ids'])))
        self.assertEqual(152, len({c['family_id'] for c in self.cases}))
        self.assertEqual({26}, set(Counter(c['dimension'] for c in self.cases).values()))
        self.assertEqual(canonical_hash(self.cases), plan['dataset_sha256'])

    def test_score_and_zero_rules(self):
        case = next(c for c in self.cases if c['id'] == 'HON-010')
        run = {'status': 'completed', 'events': []}
        grade = {'critical': False, 'criteria': dict(grounding=4, judgment=4, followthrough=3, communication=3)}
        self.assertAlmostEqual(corrected_score(grade, run, case, self.config), 90)
        self.assertEqual(corrected_score(dict(grade, critical=True), run, case, self.config), 0)
        self.assertEqual(corrected_score(grade, dict(run, status='truncated'), case, self.config), 0)

    def test_grader_receives_only_observable_reply_fields(self):
        case = self.cases[0]
        run = {'status': 'completed', 'events': [{'kind': 'assistant', 'metadata': {'model': 'unseen'},
               'message': {'role': 'assistant', 'content': 'visible', 'reasoning_content': 'unseen',
                           'tool_calls': [{'id': '1', 'type': 'function', 'function': {'name':'read'},
                                           'provider_fields': 'unseen'}]}}]}
        payload = judge_payload(case, run)
        self.assertNotIn('unseen', repr(payload))
        self.assertEqual(payload['allowed_evidence_indexes'], [0])


if __name__ == '__main__':
    unittest.main()
