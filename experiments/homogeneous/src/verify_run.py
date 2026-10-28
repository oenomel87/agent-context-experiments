"""Independent native-role and byte-exact delegation/delivery audit."""
import argparse,json,hashlib
from pathlib import Path
from collections import Counter
import contracts
from session_audit import audit_native,rollout_index

def read(p):return json.loads(Path(p).read_text())
def hb(b):return hashlib.sha256(b).hexdigest()
def h(p):return hb(Path(p).read_bytes())
def wire(x):return json.dumps(x,ensure_ascii=False,separators=(',',':'))
def verify(run):
 run=Path(run).resolve();snap=run/'snapshots';manifest=read(run/'run-manifest.json');plan=read(snap/'data/plan.json');bps=read(snap/'data/plan-sessions.json')
 assert plan['scope']=='homogeneous_primary' and len(plan['jobs'])==1090
 for rel,digest in manifest['files'].items():assert h(snap/('adapter/'+Path(rel).name) if Path(rel).is_absolute() else snap/rel)==digest,rel
 for role,sha in manifest['instructions_sha256'].items():assert h(run/f'instructions-{role}.txt')==sha
 jobs={j['job_id']:j for j in plan['jobs']};records={p.stem:read(p) for p in (run/'records').glob('*.json')};assert set(records)<=set(jobs)
 texts={t['submission_id']:t for t in read(snap/'data/stimuli.json')+[read(snap/'data/neutral-probe.json')]};threads={};usage=Counter();unknown=0;deliveries=0;eval_hashes={}
 for jid,r in records.items():
  j=jobs[jid]
  for k in ['job_id','arm','role','stage','session_key','session_turn','submission_id']:assert j[k]==r[k]
  if r['status']=='blocked':assert r['response'] is None and not (run/'claims'/(jid+'.json')).exists();continue
  req=read(run/'requests'/(jid+'.json'));assert h(run/'requests'/(jid+'.json'))==r['request_sha256']
  text={k:texts[j['submission_id']][k] for k in ['submission_id','author_id','text']}
  if j['stage']=='route':expected={'event':'user_evaluation_request','request_id':j['request_id'],'current_submission':text}
  elif j['stage']=='deliver':
   ev=records[j['evaluation_job_id']];assert ev['status']=='completed'
   expected={'event':'evaluation_completed','request_id':j['request_id'],'evaluation_id':j['evaluation_id'],'evaluation':ev['response']}
  else:
   expected={'current_submission':text}
   if j['arm']=='M':
    route=records[j['route_job_id']];assert route['status']=='completed' and route['response']=={'action':'delegate','request_id':j['request_id']}
    oq=read(run/'requests'/(j['route_job_id']+'.json'));assert oq['payload']['current_submission']==text
    assert r['original_request_sha256']==route['request_sha256']
  assert json.loads(req['prompt'])==req['payload']==expected
  assert list(json.loads(req['prompt']))==list(expected)
  assert req['prompt']==wire(json.loads(req['prompt']))
  if j['stage']=='evaluate':assert req['prompt']==wire(expected)
  assert hb(req['prompt'].encode())==req['prompt_sha256']==r['prompt_sha256']
  assert hb(req['instructions'].encode())==req['instructions_sha256']==manifest['instructions_sha256'][j['role']]
  assert req['schema']==read(snap/'schemas'/({'route':'route','deliver':'deliver','evaluate':'evaluation'}[j['stage']]+'.schema.json'))
  assert r['original_submission_sha256']==hb(wire(text).encode())
  assert read(run/'claims'/(jid+'.json'))['request_sha256']==r['request_sha256']
  if r['status']=='completed':
   contracts.validate_response(j,r['response'],texts[j['submission_id']],records)
   assert hb(r['response_text'].encode())==r['response_sha256'] and json.loads(r['response_text'])==r['response']
   trace=run/'traces'/j['session_key'];step=j['session_turn'];meta=read(trace/f'step-{step:03d}.metadata.json')
   assert meta['selected_model']==r['model_id']==r['selected_model']=='gpt-6-luna' and meta['effort']=='medium'
   assert meta['thread_id']==r['thread_id'] and meta['turn_id']==r['turn_id']
   events=[json.loads(x) for x in (trace/f'step-{step:03d}.events.jsonl').read_text().splitlines() if x.strip()]
   assert all(x.get('item_type') in (None,'agent_message','reasoning','error') for x in events)
   assert any(x['type']=='turn.completed' for x in events)
   messages=[x['text'] for x in events if x.get('item_type')=='agent_message' and x.get('text') and x['type']=='item.completed']
   assert messages and messages[-1]==r['response_text']
   pe=read(trace/'permission-evidence.json');assert pe['canary_read_denied'] and pe['network']=='restricted'
   assert read(trace/'session.json')['instructions_sha256']==manifest['instructions_sha256'][j['role']]
   previous=read(trace/f'step-{step-1:03d}.metadata.json')['raw_cumulative_usage'] if step>1 else None
   assert r['usage']=={k:v-(previous[k] if previous else 0) for k,v in meta['raw_cumulative_usage'].items()}
   if j['stage']=='evaluate':
    assert r['flags']==contracts.flags(r['response'],texts[j['submission_id']])
    assert r['evaluation_payload_sha256']==r['prompt_sha256']
    key=j['submission_id'];value=(req['prompt_sha256'],req['instructions_sha256'],hb(wire(req['schema']).encode()))
    if key in eval_hashes:assert eval_hashes[key]==value,'S/B/I evaluation input differs'
    eval_hashes[key]=value
   if j['stage']=='deliver':
    source=records[j['evaluation_job_id']];file=run/'deliveries'/(jid+'.json')
    assert file.read_bytes()==source['response_text'].encode()
    assert h(file)==r['delivery_sha256']==r['delivered_sha256']==r['delivery_source_sha256']==source['response_sha256']
    e=read(run/'delivery-evidence'/(jid+'.json'));assert e['evaluation_job_id']==j['evaluation_job_id'] and e['source_sha256']==e['delivered_sha256']==h(file)
    deliveries+=1
  else:assert r['response'] is None
  if r.get('thread_id'):
   if r['thread_id'] in threads:assert threads[r['thread_id']]==j['session_key']
   threads[r['thread_id']]=j['session_key']
  if r.get('usage') is None:unknown+=1
  else:
   for k,v in r['usage'].items():
    if type(v)is int:usage[k]+=v
 rollout_index();native=[];incomplete=[];preambles=set();commentary=Counter()
 for bp in bps:
  rs=[records.get(j) for j in bp['ordered_jobs']]
  if not all(r and r['status']=='completed' for r in rs):incomplete.append(bp['session_key']);continue
  tids={r['thread_id'] for r in rs};assert len(tids)==1 and len({r['turn_id'] for r in rs})==bp['turns']
  assert [r['sdk_step'] for r in rs]==list(range(1,bp['turns']+1))
  pairs=[(read(run/'requests'/(r['job_id']+'.json'))['prompt'],r['response']) for r in rs]
  output=run/'native-evidence'/(bp['session_key']+'.json')
  if output.exists():
   e=read(output);assert e['thread_id']==rs[0]['thread_id'] and len(e['final_messages'])==2*len(pairs)
   for i,(p,a) in enumerate(pairs):assert e['final_messages'][2*i]['text']==p and json.loads(e['final_messages'][2*i+1]['text'])==a
  else:e=audit_native(rs[0]['thread_id'],pairs,output)
  preambles.update(e['static_preamble_sha256']);commentary[bp['role']]+=e['commentary_count']
  native.append({'session_key':bp['session_key'],'arm':bp['arm'],'role':bp['role'],'turns':bp['turns'],'thread_id':rs[0]['thread_id'],'commentary_count':e['commentary_count']})
 assert preambles<=set(read(run/'preflight.json')['static_preamble_hashes'])
 if len(records)==1090 and all(r['status']=='completed' for r in records.values()):
  assert len(native)==len(threads)==470 and deliveries==220 and len(eval_hashes)==21
  assert Counter((n['arm'],n['role'],n['turns']) for n in native)=={('I','evaluator',1):210,('S','evaluator',11):20,('M','coordinator',22):20,('M','evaluator',1):220}
 result={'status':'passed','planned':1090,'recorded':len(records),'unrecorded':1090-len(records),'statuses':dict(Counter(r['status'] for r in records.values())),'unique_threads':len(threads),'fully_verified_native_sessions':len(native),'native_topology':dict(Counter(n['arm']+'/'+n['role']+'/'+str(n['turns']) for n in native)),'verified_exact_deliveries':deliveries,'identical_evaluator_payloads_by_submission':len(eval_hashes),'usage_observed':dict(usage),'usage_unknown_attempts':unknown,'commentary_messages_by_role':dict(commentary),'incomplete_sessions':incomplete,'sessions':native,'auxiliary_calls':0,'scope':'Native final turns and retained public commentary, actual source/delivery bytes, identical evaluator inputs, role instructions/model/permissions/usage; not score correctness or hidden-state equivalence.'}
 (run/'integrity-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');return result
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();r=verify(a.run);print(json.dumps({k:v for k,v in r.items() if k not in ('sessions','incomplete_sessions')},ensure_ascii=False))
