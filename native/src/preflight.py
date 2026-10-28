"""Ten separate technical calls to verify memory continuity and S2/M2 native role topology."""
import asyncio,json,hashlib,uuid,argparse
from pathlib import Path
import contracts
from session_audit import audit_native
ROOT=contracts.ROOT
HELDOUT=[{'submission_id':'technical-a','author_id':'technical-author-a','text':'비품 선반을 매주 금요일에 확인하자는 제안이다. 지난달에는 부족한 물품이 두 번 발견됐지만 확인 요일과의 관계는 조사하지 않았다. 우선 시험 운영하면서 부족한 물품의 수를 기록할 필요가 있다.'}, {'submission_id':'technical-b','author_id':'technical-author-b','text':'임시 자료실의 안내판을 입구에 두자는 제안이다. 처음 온 방문자 한 명이 위치를 물었지만 다른 사람의 경험은 확인하지 않았다. 안내판을 설치하면 모든 방문자가 불편 없이 이용할 수 있다고 단정하기는 어렵다.'}]
def save(p,x):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('x') as f:json.dump(x,f,ensure_ascii=False,indent=2);f.write('\n')
def h(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
async def main(out):
 out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
 if (out/'preflight-summary.json').exists():raise RuntimeError('existing preflight preserved')
 calls=[];audits=[];thread_ids=[];factory=contracts.load_adapter()
 async def step(session,label,payload,sch,instructions,stage=None,submission=None):
  prompt=payload if isinstance(payload,str) else json.dumps(payload,ensure_ascii=False,separators=(',',':'))
  save(out/'requests'/(label+'.json'),{'prompt':prompt,'schema':sch,'instructions_sha256':hashlib.sha256(instructions.encode()).hexdigest()})
  result=await session.step(prompt,sch,90);response=json.loads(result['text'])
  assert result['status']=='completed' and result['selected_model']=='gpt-6-luna'
  if stage:contracts.validate_response(stage,response,submission)
  save(out/'records'/(label+'.json'),{'result':result,'response':response,'prompt':prompt});calls.append({'label':label,**result})
  return prompt,response
 # Marker never appears in the second request or schema; successful recall requires the earlier user turn.
 instruction='외부 도구 없이 사용자 요청에 JSON value 문자열 하나로 답한다.'
 marker='native-check-'+uuid.uuid4().hex
 async with factory() as a:
  session=await a.start_session(instruction,'technical',out/'traces/memory')
  p1=await step(session,'memory-1','검증 표식은 '+marker+' 이다. 이를 기억하고 지금은 value에 stored만 출력하라.',{'type':'object','additionalProperties':False,'required':['value'],'properties':{'value':{'type':'string','enum':['stored']}}},instruction)
  p2=await step(session,'memory-2','앞선 사용자 요청에서 알려준 검증 표식을 value에 정확하게 출력하라.',{'type':'object','additionalProperties':False,'required':['value'],'properties':{'value':{'type':'string'}}},instruction)
  assert marker not in p2[0] and p2[1]['value']==marker
  ids={x['thread_id'] for x in calls};assert len(ids)==1;thread_ids+=list(ids)
 audits.append(audit_native(thread_ids[-1],[p1,p2],out/'native/memory.json'))
 instruction=contracts.instructions()
 # Real analysis/judge schema changes in one persistent thread.
 pairs=[]
 async with factory() as a:
  session=await a.start_session(instruction,'evaluation',out/'traces/single')
  for n,t in enumerate(HELDOUT,1):
   ap=await step(session,f'single-{n}-analysis',contracts.payload({'stage':'analyze'},t),contracts.schema('analyze'),instruction,'analyze',t);pairs.append(ap)
   jp=await step(session,f'single-{n}-judge',contracts.payload({'stage':'judge','analysis_job_id':'technical'},t,ap[1]),contracts.schema('judge'),instruction,'judge',t);pairs.append(jp)
  sid=session.thread_id;thread_ids.append(sid)
 audits.append(audit_native(sid,pairs,out/'native/single.json'))
 # Persistent analyst and two entirely new judges. Judge results never reach analyst.
 apairs=[]
 async with factory() as a:
  analyst=await a.start_session(instruction,'evaluation',out/'traces/analyst')
  for n,t in enumerate(HELDOUT,1):
   ap=await step(analyst,f'multi-{n}-analysis',contracts.payload({'stage':'analyze'},t),contracts.schema('analyze'),instruction,'analyze',t);apairs.append(ap)
   async with factory() as ja:
    judge=await ja.start_session(instruction,'evaluation',out/f'traces/judge-{n}')
    jp=await step(judge,f'multi-{n}-judge',contracts.payload({'stage':'judge','analysis_job_id':'technical'},t,ap[1]),contracts.schema('judge'),instruction,'judge',t)
    jid=judge.thread_id;thread_ids.append(jid)
   audits.append(audit_native(jid,[jp],out/f'native/judge-{n}.json'))
  aid=analyst.thread_id;thread_ids.append(aid)
 audits.append(audit_native(aid,apairs,out/'native/analyst.json'))
 assert len(calls)==10 and len(thread_ids)==len(set(thread_ids))==5
 sdkroot=ROOT.parent/'backend/src'
 proof={'status':'passed','technical_model_calls':10,'main_model_calls':0,'unique_threads':5,'native_turn_counts':sorted(a['turn_count'] for a in audits),'marker_recall_passed':True,'same_session_schema_switch_passed':True,'current_only_requests_verified':True,'shared_static_preambles':sorted(set(h for a in audits for h in a['static_preamble_sha256'])),'contracts_sha256':h(ROOT/'src/contracts.py'),'adapter_sha256':h(sdkroot/'sdk_adapter.py'),'bridge_sha256':h(sdkroot/'sdk_bridge.mjs'),'wrapper_sha256':h(sdkroot/'sdk_exec_wrapper.py'),'evidence_dir':str(out),'calls':calls}
 save(out/'preflight-summary.json',proof);print(json.dumps({k:v for k,v in proof.items() if k!='calls'},ensure_ascii=False))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();asyncio.run(main(a.output))
