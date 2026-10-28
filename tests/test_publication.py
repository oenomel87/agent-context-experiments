"""Public v4 evidence consistency and arithmetic. Standard library; no provider calls."""
import json,sys,unittest,hashlib,os
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'));sys.path.insert(0,str(ROOT/'experiments/homogeneous/src'))
from recompute import recompute,rows
from check_publication import check
import contracts
class PublicationTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.h=rows(ROOT/'experiments/homogeneous/observations.jsonl');cls.a=rows(ROOT/'experiments/alternating/observations.jsonl');cls.base=[r for r in cls.h if r['arm']=='I'];cls.calculated=recompute()
 def test_no_baseline_double_counting(self):
  self.assertEqual((len(self.h),len(self.a),len(self.base)),(1090,880,210));self.assertFalse({r['job_id'] for r in self.h}&{r['job_id'] for r in self.a});self.assertFalse(any(r['arm']=='I' for r in self.a));self.assertEqual(self.calculated['unique_valid_evaluations'],1078);self.assertEqual(self.calculated['canonical_statuses'],{'completed':1930,'failed':6,'blocked':34})
  source=json.loads((ROOT/'experiments/alternating/data/baseline-source.json').read_text());self.assertEqual(set(source['job_ids']),{r['job_id'] for r in self.base})
 def test_public_rows_match_plan_and_dependencies(self):
  for label,data in [('homogeneous',self.h),('alternating',self.base+self.a)]:
   plan=json.loads((ROOT/'experiments'/label/'data/plan.json').read_text());jobs={j['job_id']:j for j in plan['jobs']};rr={r['job_id']:r for r in data};self.assertEqual(set(rr),set(jobs))
   for jid,r in rr.items():
    for k,v in jobs[jid].items():self.assertEqual(r[k],v,(label,jid,k))
    if r['status']=='completed':self.assertTrue(all(rr[x]['status']=='completed' for x in r['requires']))
    if r['status']=='blocked':self.assertTrue(any(rr[x]['status']!='completed' for x in r['requires']));self.assertIsNone(r['response']);self.assertIsNone(r['usage'])
 def test_original_response_bytes_hash_and_role_contracts(self):
  texts={t['submission_id']:t for t in json.loads((ROOT/'experiments/homogeneous/data/stimuli.json').read_text())+[json.loads((ROOT/'experiments/homogeneous/data/neutral-probe.json').read_text())]}
  for data in [self.h,self.base+self.a]:
   rr={r['job_id']:r for r in data}
   for r in data:
    if r['status']=='completed':
     self.assertEqual(json.loads(r['response_text']),r['response']);self.assertEqual(hashlib.sha256(r['response_text'].encode()).hexdigest(),r['response_sha256']);contracts.validate_response(r,r['response'],texts[r['submission_id']],rr)
     if r['stage']=='deliver':self.assertTrue(r['delivery_verified_locally']);self.assertEqual(r['delivered_response_sha256'],rr[r['evaluation_job_id']]['response_sha256'])
    elif r.get('raw_response'):
     with self.assertRaises(ValueError):contracts.validate_response(r,json.loads(r['raw_response']),texts[r['submission_id']],rr)
 def test_full_analysis_and_fresh_or_persistent_session_aliases(self):
  bindings={};reverse={};turns=set()
  for r in self.h+self.a:
   if r.get('thread_id'):
    tid=r['thread_id'];key=r['session_key'];self.assertTrue(tid.startswith('provider-thread-'));self.assertEqual(bindings.setdefault(key,tid),tid);self.assertEqual(reverse.setdefault(tid,key),key);pair=(tid,r['turn_id']);self.assertNotIn(pair,turns);turns.add(pair)
   if r['stage']=='evaluate' and r['status']=='completed':self.assertIn('analysis',r['response']);self.assertIn('reason',r['response'])
   if r['arm']=='I' or r['arm']=='M' and r['role']=='evaluator':self.assertEqual(r['session_turn'],1)
 def test_expected_means_sd_and_matched_contrasts(self):
  h,a=self.calculated['homogeneous'],self.calculated['alternating']
  for label,result in [('homogeneous',h),('alternating',a)]:
   original=json.loads((ROOT/'experiments'/label/'reported-summary.json').read_text())
   for k,c in original['cells'].items():
    for field in ['neutral','neutral_delta','current_delta','neutral_delivered']:
     for stat in ['n','mean','sd']:self.assertAlmostEqual(result['cells'][k][field][stat],c[field][stat])
  self.assertEqual(h['contrasts']['D']['stats']['mean'],1.875);self.assertEqual(a['contrasts']['D']['stats']['mean'],-.125);self.assertEqual(a['contrasts']['S']['common_stats']['mean'],-.25);self.assertEqual(a['pooled_current_delta_by_tone']['S_cool']['mean'],1.48);self.assertEqual(a['pooled_current_delta_by_tone']['S_warm']['mean'],-.17)
  self.assertEqual(h['delivered'],211);self.assertEqual(a['delivered'],213);self.assertEqual(a['usage_by_role']['M/coordinator']['unknown_usage_attempts'],1)
 def test_published_machine_summary_recomputes_exactly(self):self.assertEqual(json.loads(json.dumps(self.calculated)),json.loads((ROOT/'reports/recomputed-summary.json').read_text()))
 def test_failure_and_interruption_accounting(self):
  a=json.loads((ROOT/'reports/execution-accounting.json').read_text());extra=json.loads((ROOT/'reports/interruption-excluded-records.json').read_text());self.assertEqual(len(extra),3);self.assertEqual(a['canonical_statuses'],self.calculated['canonical_statuses']);self.assertEqual(a['unique_valid_evaluations'],1078);self.assertEqual(a['total_sdk_call_attempts_including_technical_and_interruption'],1930+6+9+9);self.assertEqual(sum(r.get('sdk_error_type')=='ABORT_ERR' for r in self.a),1)
 def test_no_private_artifacts(self):self.assertEqual(check()['issues'],[])
 def test_live_backend_opt_in(self):
  with patch.dict(os.environ,{'EXPERIMENT_ENABLE_LIVE':'0'}):
   with self.assertRaisesRegex(RuntimeError,'opt-in'):contracts.load_adapter()
if __name__=='__main__':unittest.main()
