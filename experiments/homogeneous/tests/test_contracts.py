import unittest,sys,json,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
import contracts,boundary,session_audit
class ContractTests(unittest.TestCase):
 def test_all_evaluator_inputs_identical_and_no_external_analysis(self):
  plan=json.loads((ROOT/'data/plan.json').read_text());texts={t['submission_id']:t for t in json.loads((ROOT/'data/stimuli.json').read_text())+[json.loads((ROOT/'data/neutral-probe.json').read_text())]}
  for j in plan['jobs']:
   if j['stage']!='evaluate':continue
   rec={j['route_job_id']:{'status':'completed','response':{'action':'delegate','request_id':j['request_id']}}} if j['arm']=='M' else {}
   p=contracts.make_payload(j,texts[j['submission_id']],rec)
   self.assertEqual(boundary.canonical(p),boundary.canonical(boundary.evaluation_payload(texts[j['submission_id']])))
   self.assertEqual(set(p),{'current_submission'})
 def test_native_audit_retains_commentary_without_confusing_final(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'fixture.jsonl';tid='offline-fixture';request='request';response={'ok':True}
   lines=[{'type':'session_meta','payload':{'id':tid}},{'type':'turn_context','payload':{'turn_id':'turn1','model':'gpt-6-luna','effort':'medium'}},{'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':request}]}},{'type':'response_item','payload':{'type':'message','role':'assistant','phase':'commentary','content':[{'type':'output_text','text':'intermediate visible message'}]}},{'type':'response_item','payload':{'type':'message','role':'assistant','phase':'final_answer','content':[{'type':'output_text','text':json.dumps(response)}]}}]
   p.write_text('\n'.join(json.dumps(x) for x in lines));session_audit.CACHE[tid]=p
   proof=session_audit.audit_native(tid,[(request,response)])
   self.assertEqual(proof['commentary_count'],1);self.assertEqual(len(proof['final_messages']),2);self.assertEqual(len(proof['visible_messages']),3)
   lines.append(lines[-1]);p.write_text('\n'.join(json.dumps(x) for x in lines))
   with self.assertRaises(AssertionError):session_audit.audit_native(tid,[(request,response)])
   session_audit.CACHE.pop(tid)
if __name__=='__main__':unittest.main()
