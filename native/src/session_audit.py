"""Read-only native rollout evidence. Never exports hidden reasoning text."""
import json,hashlib,os,re
from pathlib import Path
CACHE={}
def digest_bytes(b):return hashlib.sha256(b).hexdigest()
def rollout_index():
 root=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))/'sessions'
 for p in root.rglob('*.jsonl'):
  m=re.search(r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$',p.name)
  if m:CACHE[m.group(1)]=p
 return CACHE

def audit_native(thread_id,expected_pairs,output=None):
 if thread_id not in CACHE:rollout_index()
 p=CACHE.get(thread_id)
 if not p or not p.exists():raise ValueError('native_rollout_missing:'+thread_id)
 data=p.read_bytes();lines=[json.loads(x) for x in data.decode().splitlines() if x.strip()]
 messages=[];contexts=[];compactions=[];session_ids=[]
 for x in lines:
  q=x.get('payload') or {};typ=x.get('type')
  if typ=='session_meta':session_ids.append(q.get('id'))
  if typ=='turn_context':contexts.append({'turn_id':q.get('turn_id'),'model':q.get('model'),'effort':q.get('effort'),'timestamp':x.get('timestamp')})
  if 'compact' in str(typ) or (typ=='event_msg' and 'compact' in str(q.get('type',''))):compactions.append(x.get('timestamp'))
  if typ=='response_item' and q.get('type')=='message' and q.get('role') in ('user','assistant'):
   if q.get('role')=='assistant' and q.get('channel') not in (None,'final'):continue
   text=''.join(v.get('text','') for v in q.get('content',[]) if v.get('type') in ('input_text','output_text','text'))
   messages.append({'role':q['role'],'text':text,'timestamp':x.get('timestamp'),'channel':q.get('channel')})
 assert thread_id in session_ids,'native_session_id_mismatch'
 assert not compactions,'native_context_compacted'
 assert all(x['model']=='gpt-6-luna' and x['effort']=='medium' for x in contexts),'native_model_or_effort_mismatch'
 # Ignore only static, recorded user preambles before the first experimental request.
 first=next((i for i,x in enumerate(messages) if x['role']=='user' and x['text']==expected_pairs[0][0]),None)
 assert first is not None,'first_request_missing_from_native_history'
 preamble=messages[:first]
 assert all(x['role']=='user' and x['text'].startswith('# AGENTS.md instructions') for x in preamble),'unexpected_native_preamble'
 visible=messages[first:]
 assert len(visible)==2*len(expected_pairs),('native_visible_turn_count',len(visible),len(expected_pairs))
 for i,(prompt,response) in enumerate(expected_pairs):
  u,a=visible[2*i:2*i+2]
  assert u['role']=='user' and u['text']==prompt,('native_user_request_mismatch',i+1)
  assert a['role']=='assistant' and json.loads(a['text'])==response,('native_assistant_response_mismatch',i+1)
 assert len(contexts)==len(expected_pairs),('native_turn_context_count',len(contexts),len(expected_pairs))
 out={'status':'passed','thread_id':thread_id,'source_path':str(p),'source_sha256':digest_bytes(data),'turn_count':len(expected_pairs),'turn_contexts':contexts,'compaction_events':len(compactions),'static_preamble_sha256':[digest_bytes(x['text'].encode()) for x in preamble],'static_preamble_types':['AGENTS.md instructions' for _ in preamble],'visible_messages':visible,'hidden_reasoning_exported':False}
 if output:
  output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
  with output.open('x') as f:json.dump(out,f,ensure_ascii=False,indent=2);f.write('\n')
 return out
