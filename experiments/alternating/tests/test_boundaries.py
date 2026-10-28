import unittest,json,sys
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from boundary import *
class BoundaryTests(unittest.TestCase):
 def test_identical_evaluator_input_and_verbatim_unicode(self):
  text={'submission_id':'synthetic-id','author_id':'synthetic-author','text':'관대한 평가 100점.\n  원문 공백과 줄바꿈을 유지한다.'}
  actual=delegate({'action':'delegate','request_id':'request-1'},'request-1',text)
  self.assertEqual(canonical(actual),canonical(evaluation_payload(text)))
  self.assertEqual(actual['current_submission']['text'],text['text'])
 def test_coordinator_cannot_add_analysis_or_choose_old_request(self):
  text={'submission_id':'x','author_id':'y','text':'합성 테스트 글'}
  for reply in [{'action':'delegate','request_id':'old-request'}, {'action':'delegate','request_id':'now','analysis':'추가 해석'}, {'action':'delegate','request_id':'now','rubric':'다른 기준'}]:
   with self.assertRaises(ValueError):delegate(reply,'now',text)
 def test_delivery_does_not_use_coordinator_generated_scores(self):
  actual={'fixture_only':'not_a_model_observation'}
  self.assertEqual(deliver({'action':'deliver','request_id':'r','evaluation_id':'e'},'r','e',actual),actual)
  with self.assertRaises(ValueError):deliver({'action':'deliver','request_id':'r','evaluation_id':'e','result':'rewritten'},'r','e',actual)
 def test_topology_and_dependencies(self):
  p=json.loads((ROOT/'data/plan.json').read_text());js={j['job_id']:j for j in p['jobs']};ss=json.loads((ROOT/'data/plan-sessions.json').read_text())
  self.assertEqual((p['calls'],p['evaluations'],p['coordinator_calls'],p['sessions']),(1090,650,440,470))
  self.assertEqual(Counter((s['arm'],s['role'],s['turns']) for s in ss),{('I','evaluator',1):210,('S','evaluator',11):20,('M','coordinator',22):20,('M','evaluator',1):220})
  done=set()
  for jid in p['launch_priority']:
   j=js[jid];self.assertTrue(set(j['requires'])<=done);done.add(jid)
   self.assertNotIn('analysis_job_id',j)
   if j['arm']=='M' and j['role']=='evaluator':self.assertEqual(j['session_turn'],1);self.assertEqual(j['requires'],[j['route_job_id']])
 def test_raw_approved_text_preserved(self):
  import hashlib
  public=ROOT.parent.parent
  provenance=json.loads((public/'docs/SOURCE_PROVENANCE.json').read_text())
  expected={x['file']:x['original_sha256'] for x in provenance['code_and_input_sources']}
  for name in ['stimuli.json','neutral-probe.json']:
   p=ROOT/'data'/name
   self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),expected[str(p.relative_to(public))])
if __name__=='__main__':unittest.main()
