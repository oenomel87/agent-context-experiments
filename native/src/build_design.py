"""Offline plans: main 1,090 calls; auxiliary 900 extra or 1,110 standalone. No models."""
import json,hashlib,random,shutil
from pathlib import Path
from collections import Counter
R=Path(__file__).resolve().parents[1];W=R.parent
SOURCE=R/'data/source'
def read(p):return json.loads(p.read_text())
def save(p,v):(R/p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def uid(s):return hashlib.sha256(('session-context-v3/'+s).encode()).hexdigest()[:20]
def build():
 texts=read(SOURCE/'stimuli.json');probe=read(SOURCE/'neutral-probe.json')
 # Reuse approved text, never previous scores.
 for t in texts+[probe]:t.pop('model_assessment',None)
 save('data/stimuli.json',texts);save('data/neutral-probe.json',probe)
 rubric=read(SOURCE/'rubric.json')
 rubric['instructions'][0]='평가 요청의 current_submission 글 하나만 평가한다. 앞선 실제 대화 또는 제공된 history는 이전 작성자들의 글과 실제 평가 기록이다.'
 save('data/rubric.json',rubric)
 shutil.copyfile(SOURCE/'assessment.schema.json',R/'data/assessment.schema.json')
 # Base IDs may be H01..10; map ordered cases by exact approved source mapping.
 reviewed=read(SOURCE/'history-texts.json')
 lookup={(t['base_id'],t['tone']):t['submission_id'] for t in reviewed}
 orders=[[(x+r)%10 for x in [0,1,9,2,8,3,7,4,6,5]] for r in range(10)]
 jobs=[];episodes=[]
 def add(arm,rep,tone,depth,position,stage,sid,session,session_turn,deps,**extra):
  j={'job_id':uid(f'{arm}/{rep}/{tone}/{depth}/{position}/{stage}'),'arm':arm,'replicate':rep,'tone':tone,'checkpoint_depth':depth,'position':position,'stage':stage,'submission_id':sid,'session_key':session,'session_turn':session_turn,'requires':list(deps),**extra};jobs.append(j);return j['job_id']
 for rep,order in enumerate(orders,1):
  baselines={}
  for t in texts+[probe]:
   sid=t['submission_id'];baselines[sid]=add('I',rep,None,None,None,'judge',sid,uid(f'I/{rep}/{sid}'),1,[],job_key_suffix=sid)
   # I jobs require IDs per text rather than the generic positional key.
   jobs[-1]['job_id']=uid(f'I/{rep}/{sid}');baselines[sid]=jobs[-1]['job_id']
  for tone in ('warm','cool'):
   sids=[lookup[(f'H{i+1:02}',tone)] for i in order]
   episodes.append({'replicate':rep,'tone':tone,'order':order,'submission_ids':sids})
   chain10=[]
   for depth in [1,5,10]:
    session=uid(f'T/{rep}/{tone}/stop{depth}');history=[]
    for pos,sid in enumerate(sids[:depth],1):
     jid=add('T',rep,tone,depth,pos,'judge',sid,session,pos,history[-1:],baseline_job_id=baselines[sid],native_prior_jobs=history.copy(),is_primary_current_series=depth==10)
     history.append(jid)
    pj=add('T',rep,tone,depth,depth+1,'probe',probe['submission_id'],session,depth+1,history[-1:],baseline_job_id=baselines[probe['submission_id']],native_prior_jobs=history.copy(),terminal=True)
    add('R_match',rep,tone,depth,depth+1,'probe',probe['submission_id'],uid(f'Rprobe/{rep}/{tone}/{depth}'),1,history.copy(),baseline_job_id=baselines[probe['submission_id']],paired_native_job_id=pj,replay_source_jobs=history.copy(),replay_format='legacy_history_json_from_native_visible_records',source_current_job_id=pj)
    if depth==10:chain10=history
   for pos,(sid,tjid) in enumerate(zip(sids,chain10),1):
    add('R_match',rep,tone,10,pos,'judge',sid,uid(f'Rcurrent/{rep}/{tone}/{pos}'),1,chain10[:pos-1],baseline_job_id=baselines[sid],paired_native_job_id=tjid,replay_source_jobs=chain10[:pos-1],replay_format='legacy_history_json_from_native_visible_records',source_current_job_id=tjid)
   # Existing free-running replay: each fresh request uses its own prior assessments.
   free=[]
   for pos,sid in enumerate(sids,1):
    fj=add('R_free',rep,tone,10,pos,'judge',sid,uid(f'Rfree/{rep}/{tone}/{pos}'),1,free.copy(),baseline_job_id=baselines[sid],replay_source_jobs=free.copy(),replay_format='legacy_history_json_from_own_visible_records')
    free.append(fj)
    if pos in (1,5,10):
     add('R_free',rep,tone,pos,pos+1,'probe',probe['submission_id'],uid(f'Rfreeprobe/{rep}/{tone}/{pos}'),1,free.copy(),baseline_job_id=baselines[probe['submission_id']],replay_source_jobs=free.copy(),replay_format='legacy_history_json_from_own_visible_records',terminal=True)
   # S2 and M2 have identical role operations and two calls per assessed essay.
   for arm in ('S2','M2'):
    previous_a=None;previous_j=None;analyses=[];judgments=[]
    session_a=uid(f'{arm}/analyst/{rep}/{tone}')
    session_s=uid(f'{arm}/shared/{rep}/{tone}')
    for pos,sid in enumerate(sids+[probe['submission_id']],1):
     isprobe=pos==11
     adeps=[previous_j] if arm=='S2' and previous_j else ([previous_a] if previous_a else [])
     aj=add(arm,rep,tone,10,pos,'analyze',sid,session_s if arm=='S2' else session_a,2*pos-1 if arm=='S2' else pos,adeps,is_probe=isprobe,prior_analysis_jobs=analyses.copy(),prior_judgment_jobs=judgments.copy() if arm=='S2' else [])
     jj=add(arm,rep,tone,10,pos,'probe' if isprobe else 'judge',sid,session_s if arm=='S2' else uid(f'M2/judge/{rep}/{tone}/{pos}'),2*pos if arm=='S2' else 1,[aj],analysis_job_id=aj,baseline_job_id=baselines[sid],is_probe=isprobe,prior_judgment_jobs=judgments.copy() if arm=='S2' else [],terminal=isprobe)
     previous_a,previous_j=aj,jj;analyses.append(aj);judgments.append(jj)
 counts=Counter(j['arm'] for j in jobs);assert counts=={'I':210,'T':380,'R_match':260,'R_free':260,'S2':440,'M2':440}
 assert len(jobs)==1990 and len({j['job_id'] for j in jobs})==1990
 index={j['job_id']:j for j in jobs}
 # Source current user text can be prepared from frozen data; R never reads its paired current answer.
 for j in jobs:
  assert all(d in index for d in j['requires'])
  if j['arm']=='R_match':
   assert j['paired_native_job_id'] not in j['replay_source_jobs']
   assert all(index[x]['arm']=='T' and index[x]['stage']=='judge' for x in j['replay_source_jobs'])
  if j['arm']=='M2' and j['stage']!='analyze':assert j['session_turn']==1 and not j['prior_judgment_jobs']
 sessions={}
 for j in jobs:sessions.setdefault(j['session_key'],[]).append(j)
 for js in sessions.values():assert sorted(j['session_turn'] for j in js)==list(range(1,len(js)+1))
 # Build a reproducible randomized dependency-respecting launch priority, within replicate blocks.
 rng=random.Random(20261025);reps=list(range(1,11));rng.shuffle(reps);schedule=[]
 for rep in reps:
  pending={j['job_id']:j for j in jobs if j['replicate']==rep};done=set()
  while pending:
   ready=sorted(k for k,j in pending.items() if set(j['requires'])<=done)
   assert ready,'dependency cycle';jid=rng.choice(ready);schedule.append(jid);done.add(jid);del pending[jid]
 main_arms={'I','S2','M2'}
 main_jobs=[j for j in jobs if j['arm'] in main_arms]
 aux_jobs=[j for j in jobs if j['arm'] not in main_arms]
 baseline_jobs=[j for j in jobs if j['arm']=='I']
 def package(name,js,scope,baseline_mode):
  ids={j['job_id'] for j in js}
  ss={k:v for k,v in sessions.items() if v[0]['job_id'] in ids}
  p={'version':'session-context-v3-main-2x2-r1','status':'design_only_not_executed','scope':scope,
     'planned_calls':len(js),'planned_grade_calls':sum(j['stage']!='analyze' for j in js),
     'planned_analysis_calls':sum(j['stage']=='analyze' for j in js),
     'checkpoints':[0,10] if scope=='main_four_conditions' else [0,1,5,10],
     'random_seed':20261025,'orders':orders,'episodes':episodes,'jobs':js,
     'launch_priority':[jid for jid in schedule if jid in ids],
     'arm_counts':dict(Counter(j['arm'] for j in js)),
     'session_blueprints':len(ss),'actual_model_calls':0,'baseline_mode':baseline_mode,
     'external_baseline_job_ids':sorted({j['baseline_job_id'] for j in js if j.get('baseline_job_id') and j['baseline_job_id'] not in ids})}
  save('data/'+name+'.json',p)
  save('data/'+name+'-sessions.json',[{'session_key':k,'arm':v[0]['arm'],'replicate':v[0]['replicate'],'tone':v[0]['tone'],'turn_count':len(v),'ordered_jobs':[j['job_id'] for j in sorted(v,key=lambda j:j['session_turn'])]} for k,v in ss.items()])
  for j in js:assert set(j['requires'])<=ids
  return p
 main=package('plan',main_jobs,'main_four_conditions','fresh_common_baselines_included')
 aux=package('auxiliary-plan',aux_jobs,'auxiliary_replay_comparison','requires_bound_same_batch_main_baseline_records')
 combined=package('combined-plan',jobs,'main_plus_auxiliary','fresh_common_baselines_once')
 standalone=package('auxiliary-standalone-plan',baseline_jobs+aux_jobs,'auxiliary_standalone','fresh_baselines_included_no_old_scores')
 save('data/session-blueprints.json',read(R/'data/plan-sessions.json'))
 cells=Counter(j['arm']+'/'+j['tone'] for j in main_jobs if j['arm']!='I')
 assert len(main_jobs)==1090 and len(aux_jobs)==900 and len(baseline_jobs+aux_jobs)==1110
 assert main['session_blueprints']==470 and aux['session_blueprints']==580
 assert cells=={'S2/warm':220,'S2/cool':220,'M2/warm':220,'M2/cool':220}
 save('validation.json',{'status':'offline_structure_checks_passed','actual_model_calls':0,
     'default_execution_scope':'main_four_conditions_only',
     'main':{'calls':1090,'grade_calls':650,'analysis_calls':440,'sessions':470,'common_baseline_calls':210,'four_cell_calls':dict(cells)},
     'auxiliary':{'calls_if_common_baseline_shared':900,'sessions_if_common_baseline_shared':580,'standalone_calls_with_new_baselines':1110},
     'combined_calls_with_shared_baseline':1990,'separate_runs_with_separate_baselines':2200,
     'same_session_turns_contiguous':True,'no_probe_in_later_history':True,
     'main_has_no_replay_jobs':True,'all_job_ids_unique':True,
     'live_adapter_capabilities':'not_verified_for_new_design'})
 save('data/source-provenance.json',{'source':'data/source; approved synthetic input text reused without historical model scores','text_and_author_identity_preserved':all(next(x for x in reviewed if x['submission_id']==t['submission_id'])['text']==t['text'] for t in texts),'old_model_scores_reused':False})
 print(json.dumps(read(R/'validation.json'),ensure_ascii=False))
if __name__=='__main__':build()
