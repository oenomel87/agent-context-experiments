"""Offline export-integrity and arithmetic tests. No live provider calls."""
import json,sys,unittest,os
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from recompute import recompute,rows
from check_publication import check
class PublicationTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.calculated=recompute()
 def test_complete_selected_observations(self):
  sets=[(ROOT/'native/published/observations.jsonl',1090),(ROOT/'studies/replay-fixed/observations.jsonl',720),(ROOT/'studies/replay-cumulative/observations.jsonl',610)]
  for path,n in sets:
   data=rows(path);self.assertEqual(len(data),n);self.assertEqual(len({r['job_id'] for r in data}),n)
   self.assertTrue(all(r['status']=='completed' for r in data))
   for r in data:
    self.assertFalse({'request_path','trace_path','sdk_raw_result','raw_response','created_at','finished_at','source_path'} & set(r))
    if 'thread_id' in r:self.assertIn('-thread-',r['thread_id'])
 def test_native_matches_reported_numbers(self):
  expected=json.loads((ROOT/'native/published/reported-summary.json').read_text())
  actual=self.calculated['native']
  self.assertEqual(actual['primary'],expected['primary'])
  self.assertEqual(actual['valid_grades'],650)
  for c in expected['cells']:
   self.assertEqual(actual['cells'][c['cell']]['neutral_probe']['means']['total'],c['neutral_mean'])
   self.assertEqual(actual['contrasts']['current_minus_I'][c['cell']]['means']['total'],c['current_paired_delta'])
 def test_replay_numbers(self):
  a=self.calculated['replay_fixed']['effects'];b=self.calculated['replay_cumulative']['trajectory_summary']
  self.assertAlmostEqual(a['text_only/warm-single']['mean_target_delta'],.4166666666666667)
  self.assertAlmostEqual(a['text_and_feedback/cool-single']['mean_target_delta'],-.9375)
  self.assertAlmostEqual(b['warm']['total']['mean_k1_10']['mean'],.54)
  self.assertAlmostEqual(b['cool']['total']['mean_k1_10']['mean'],-.92)
 def test_no_private_artifacts_or_patterns(self):self.assertEqual(check()['issues'],[])
 def test_live_backend_is_opt_in(self):
  sys.path.insert(0,str(ROOT/'native/src'));import contracts
  with patch.dict(os.environ,{'EXPERIMENT_ENABLE_LIVE':'0'}):
   with self.assertRaisesRegex(RuntimeError,'opt-in'):contracts.load_adapter()
if __name__=='__main__':unittest.main()
