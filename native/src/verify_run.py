"""Independent recorded request, native transcript and exact-session audit."""
import argparse,json,hashlib
from pathlib import Path
from collections import Counter
import contracts
from session_audit import rollout_index,audit_native

def read(p):return json.loads(p.read_text())
def h(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def verify(run):
 run=Path(run).resolve();snap=run/'snapshots';m=read(run/'run-manifest.json');plan=read(snap/'data/plan.json');bp=read(snap/'data/session-blueprints.json')
 assert plan['scope']=='main_four_conditions' and len(plan['jobs'])==1090
 for rel,expected in m['files'].items():
  p=snap/('adapter/'+Path(rel).name) if Path(rel).is_absolute() else snap/rel
  assert h(p)==expected,rel
 assert h(run/'instructions.txt')==m['instructions_sha256']
 jobs={j['job_id']:j for j in plan['jobs']};records={p.stem:read(p) for p in (run/'records').glob('*.json')}
 assert set(records)<=set(jobs)
 texts={t['submission_id']:t for t in read(snap/'data/stimuli.json')+[read(snap/'data/neutral-probe.json')]}
 threads={};usage=Counter();unknown=0;errors=Counter()
 for jid,r in records.items():
  j=jobs[jid]
  for k in ('job_id','arm','tone','stage','session_key','session_turn','submission_id'):assert r[k]==j[k]
  if r['status']=='blocked':
   assert r['response'] is None and not (run/'claims'/(jid+'.json')).exists();continue
  req=read(run/'requests'/(jid+'.json'))
  assert h(run/'requests'/(jid+'.json'))==r['request_sha256']
  public={k:texts[j['submission_id']][k] for k in ('submission_id','author_id','text')}
  expected={'mode':'analyze' if j['stage']=='analyze' else 'judge'}
  if j.get('analysis_job_id'):
   ar=records[j['analysis_job_id']];assert ar['status']=='completed';expected['current_analysis']=ar['response']
  expected['current_submission']=public
  assert req['payload']==expected==json.loads(req['prompt'])
  assert list(json.loads(req['prompt']))==list(expected)
  assert hashlib.sha256(req['prompt'].encode()).hexdigest()==req['prompt_sha256']==r['prompt_sha256']
  assert hashlib.sha256(req['instructions'].encode()).hexdigest()==m['instructions_sha256']==req['instructions_sha256']
  assert req['schema']==contracts.schema(j['stage'])
  assert (run/'claims'/(jid+'.json')).exists()
  trace=run/'traces'/j['session_key'];step=j['session_turn']
  meta=trace/f'step-{step:03d}.metadata.json';events=trace/f'step-{step:03d}.events.jsonl'
  if r['status']=='completed':
   contracts.validate_response(j['stage'],r['response'],texts[j['submission_id']])
   assert r['model_id']==r['selected_model']=='gpt-6-luna'
   mm=read(meta);assert mm['selected_model']=='gpt-6-luna' and mm['effort']=='medium' and mm['thread_id']==r['thread_id'] and mm['turn_id']==r['turn_id']
   ev=[json.loads(x) for x in events.read_text().splitlines() if x.strip()]
   assert all(x.get('item_type') in (None,'agent_message','reasoning','error') for x in ev)
   assert any(x['type']=='turn.completed' for x in ev)
   messages=[x['text'] for x in ev if x.get('item_type')=='agent_message' and x.get('text') and x['type']=='item.completed']
   assert len(messages)==1 and json.loads(messages[0])==r['response']
   evidence=read(trace/'permission-evidence.json');assert evidence['canary_read_denied'] and evidence['network']=='restricted'
   assert read(trace/'session.json')['instructions_sha256']==m['instructions_sha256']
   if j['stage']=='analyze':assert r['analysis_flags']==contracts.analysis_flags(r['response'],texts[j['submission_id']])
   previous=read(trace/f'step-{step-1:03d}.metadata.json')['raw_cumulative_usage'] if step>1 else None
   raw=mm['raw_cumulative_usage']
   assert r['usage']=={k:(v-(previous[k] if previous else 0)) for k,v in raw.items()}
  else:
   assert r['response'] is None;errors[r.get('error','unknown')]+=1
  if r.get('thread_id'):
   if r['thread_id'] in threads:assert threads[r['thread_id']]==j['session_key']
   threads[r['thread_id']]=j['session_key']
  if r.get('usage') is None:unknown+=1
  else:
   for k,v in r['usage'].items():
    if type(v)is int:usage[k]+=v
 rollout_index();native=[];incomplete=[];preambles=set()
 for b in bp:
  rs=[records.get(j) for j in b['ordered_jobs']]
  if not all(r and r['status']=='completed' for r in rs):incomplete.append(b['session_key']);continue
  tids={r['thread_id'] for r in rs};assert len(tids)==1
  assert [r['sdk_step'] for r in rs]==list(range(1,b['turn_count']+1))
  assert len({r['turn_id'] for r in rs})==len(rs)
  pairs=[(read(run/'requests'/(r['job_id']+'.json'))['prompt'],r['response']) for r in rs]
  output=run/'native-evidence'/(b['session_key']+'.json')
  if output.exists():
   evidence=read(output);assert evidence['thread_id']==rs[0]['thread_id']
   assert len(evidence['visible_messages'])==2*len(pairs)
   for i,(prompt,response) in enumerate(pairs):assert evidence['visible_messages'][2*i]['text']==prompt and json.loads(evidence['visible_messages'][2*i+1]['text'])==response
  else:evidence=audit_native(rs[0]['thread_id'],pairs,output)
  preambles.update(evidence['static_preamble_sha256']);native.append({'session_key':b['session_key'],'arm':b['arm'],'tone':b['tone'],'turns':b['turn_count'],'thread_id':rs[0]['thread_id']})
 pf=read(run/'preflight.json');assert preambles<=set(pf['shared_static_preambles'])
 if len(records)==1090 and all(r['status']=='completed' for r in records.values()):
  assert len(threads)==470 and len(native)==470
  assert Counter((x['arm'],x['turns']) for x in native)=={('I',1):210,('S2',22):20,('M2',11):20,('M2',1):220}
 out={'status':'passed','planned':1090,'recorded':len(records),'unrecorded':1090-len(records),'statuses':dict(Counter(r['status'] for r in records.values())),'unique_threads':len(threads),'fully_verified_native_sessions':len(native),'native_topology':dict(Counter(x['arm']+'/'+str(x['turns']) for x in native)),'incomplete_sessions':incomplete,'usage_observed':dict(usage),'usage_unknown_attempts':unknown,'errors':dict(errors),'static_preamble_hashes':sorted(preambles),'auxiliary_calls':0,'sessions':native,'scope':'actual native user/final-assistant message sequences, session/turn identity, handoff contents, source snapshots and SDK model/permissions/usage; not score correctness'}
 (run/'integrity-check.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');return out
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();o=verify(a.run);print(json.dumps({k:v for k,v in o.items() if k not in ('sessions','incomplete_sessions')},ensure_ascii=False))
