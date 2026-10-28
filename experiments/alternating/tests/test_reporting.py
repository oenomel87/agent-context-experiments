import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('report_results', ROOT/'src/report_results.py')
reporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reporter)


class ReportingTests(unittest.TestCase):
    def test_full_fixture_counts_pairing_and_scope(self):
        plan = json.loads((ROOT/'data/plan.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run/'snapshots/data').mkdir(parents=True)
            (run/'records').mkdir()
            (run/'snapshots/data/plan.json').write_text(json.dumps(plan))
            for j in plan['jobs']:
                record = dict(j, status='completed')
                if j['stage'] == 'evaluate':
                    score = 2
                    if j['arm'] == 'S' and j.get('sequence') == 'warm_first':
                        score = 3
                    record['response'] = {'analysis': {'claim':'x', 'facts': [], 'evidence': [], 'limitations': []}, 'scores': dict.fromkeys(reporter.SCORE_KEYS, score), 'reason': 'x'}
                else:
                    record['response'] = {'scores': dict.fromkeys(reporter.SCORE_KEYS, 4)}
                (run/'records'/f"{j['job_id']}.json").write_text(json.dumps(record))
            report = reporter.build_report(run)
            self.assertEqual(report['planned_calls'], 1090)
            self.assertEqual(report['valid_evaluations'], 650)
            self.assertEqual(report['baseline']['valid_evaluations'], 210)
            self.assertEqual(report['operations_by_role']['coordinator']['planned'], 440)
            self.assertEqual(report['cells']['S_warm_first']['current_raw']['n'], 100)
            self.assertEqual(report['cells']['S_warm_first']['neutral_raw']['n'], 10)
            self.assertEqual(report['primary_neutral_contrasts']['D']['distribution']['mean'], 3)
            self.assertEqual(report['direct_S_minus_M']['warm_first']['current']['n'], 100)
            self.assertEqual(report['delivery']['verified_user_delivered'], 0)
            self.assertEqual(report['delivery']['states']['unknown'], 220)
            for filename in ('summary.json', 'overview.md', 'actual-observations.md'):
                self.assertTrue((run/'report'/filename).exists())

    def test_invalid_partial_and_blocked_not_scored(self):
        self.assertIsNone(reporter.evaluation_total({'status':'blocked'}))
        self.assertIsNone(reporter.evaluation_total({'status':'completed','response':{'scores':dict.fromkeys(reporter.SCORE_KEYS, 4)}}))
        self.assertEqual(reporter.distribution([])['mean'], None)
        self.assertEqual(reporter.distribution([1])['sd'], None)


if __name__ == '__main__':
    unittest.main()
