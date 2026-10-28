import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('report_results', ROOT/'src/report_results.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name)
        (self.run/'snapshots/data').mkdir(parents=True)
        (self.run/'records').mkdir()
        self.plan = json.loads((ROOT/'data/plan.json').read_text())
        (self.run/'snapshots/data/plan.json').write_text(json.dumps(self.plan))

    def record(self, job, value=2, **extra):
        record = dict(job, status='completed', response={'scores': {'claim_clarity': value, 'support_linkage': value, 'qualification': value}, 'reason': 'fixture'}, **extra)
        (self.run/'records'/f"{job['job_id']}.json").write_text(json.dumps(record))

    def test_zero_calls(self):
        result = module.report(self.run)
        self.assertEqual(result['observed_records'], 0)
        self.assertEqual(result['planned_calls'], 1090)
        self.assertEqual(result['primary']['D']['n'], 0)
        self.assertEqual(result['sessions']['planned_logical_sessions'], 470)
        self.assertTrue((self.run/'report/actual-observations.md').exists())

    def test_separate_probe_current_and_absolute_cancellation(self):
        for job in self.plan['jobs']:
            if job['stage'] == 'probe' and job['replicate'] in (1, 2):
                value = 2
                if job['arm'] == 'M2' and job['tone'] == 'warm':
                    value = 3 if job['replicate'] == 1 else 1
                self.record(job, value)
        result = module.report(self.run)
        self.assertEqual(result['primary']['G_M']['means']['total'], 0)
        self.assertEqual(result['primary']['G_M']['mean_absolute']['total'], 3)
        self.assertEqual(result['primary']['D']['n'], 2)
        self.assertEqual(result['cells']['M2/warm']['current_grades']['n'], 0)
        self.assertEqual(result['cells']['M2/warm']['neutral_probe']['n'], 2)

    def test_matched_baseline_and_blocked_usage(self):
        job = next(j for j in self.plan['jobs'] if j['arm'] == 'S2' and j['stage'] == 'judge')
        base = next(j for j in self.plan['jobs'] if j['job_id'] == job['baseline_job_id'])
        self.record(base, 1, usage={'input_tokens': 5})
        self.record(job, 2, usage={'input_tokens': 7}, thread_id='fixture')
        other = next(j for j in self.plan['jobs'] if j['arm'] == 'S2' and j['stage'] == 'analyze')
        (self.run/'records'/'blocked.json').write_text(json.dumps(dict(other, status='blocked')))
        result = module.report(self.run)
        self.assertEqual(result['contrasts']['current_minus_I']['S2/'+job['tone']]['means']['total'], 3)
        self.assertEqual(result['usage_per_turn']['input_tokens']['known_sum'], 12)
        self.assertEqual(result['usage_per_turn']['input_tokens']['unknown_turns'], 0)
        self.assertEqual(result['sessions']['observed_thread_count'], 1)

    def test_failure_not_zero_imputed_and_unplanned_rejected(self):
        job = next(j for j in self.plan['jobs'] if j['stage'] == 'probe')
        (self.run/'records'/'failed.json').write_text(json.dumps(dict(job, status='failed')))
        self.assertEqual(module.report(self.run)['valid_grades'], 0)
        (self.run/'records'/'bad.json').write_text(json.dumps({'job_id': 'auxiliary'}))
        with self.assertRaises(ValueError):
            module.report(self.run)


if __name__ == '__main__':
    unittest.main()
