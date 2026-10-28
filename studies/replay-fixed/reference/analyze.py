"""Paired descriptive comparisons. No gold-score claims or pseudo-independent tests."""
from collections import Counter,defaultdict
from statistics import mean
from materialize import validate_response

def summarize(plan,observations,metric="total"):
 jobs={j['job_id']:j for j in plan['target_jobs']}
 seen=set();scores={};statuses={}
 for obs in observations:
  jid=obs['job_id']
  if jid not in jobs or jid in seen:raise ValueError('unknown_or_duplicate_target_job')
  seen.add(jid);statuses[jid]=obs['status']
  if obs['status']=='completed':
   validate_response(obs['response']);scores[jid]=(sum(obs['response']['scores'].values()) if metric=='total' else obs['response']['scores'][metric])
  else:scores[jid]=None
 baseline={};indexed={}
 for j in jobs.values():
  score=scores.get(j['job_id'])
  if j['condition']=='single':baseline[(j['target_id'],j['replicate'])]=score
  else:indexed[(j['target_id'],j['replicate'],j['block'],j['tone'],j['condition'])]=score
 per_target=defaultdict(list);pair_counts=Counter();missing=Counter()
 def pair(name,key,a,b):
  if a is None or b is None:missing[name]+=1
  else:per_target[(name,key)].append(a-b);pair_counts[name]+=1
 for key,value in indexed.items():
  target,rep,block,tone,mode=key
  pair(f'{mode}/{tone}-single',target,value,baseline.get((target,rep)))
  if mode=='text_and_feedback':pair(f'feedback_bundle_increment/{tone}',target,value,indexed.get((target,rep,block,tone,'text_only')))
  if tone!='neutral':pair(f'{mode}/{tone}-neutral',target,value,indexed.get((target,rep,block,'neutral',mode)))
  if tone!='neutral' and mode=='text_and_feedback':
   v=[value,indexed.get((target,rep,block,'neutral',mode)),indexed.get((target,rep,block,tone,'text_only')),indexed.get((target,rep,block,'neutral','text_only'))]
   name=f'feedback_tone_interaction/{tone}'
   if any(x is None for x in v):missing[name]+=1
   else:per_target[(name,target)].append((v[0]-v[1])-(v[2]-v[3]));pair_counts[name]+=1
 grouped=defaultdict(dict)
 for (name,target),v in per_target.items():grouped[name][target]=mean(v)
 effects={name:{'mean_target_delta':mean(v.values()),'target_deltas':v,'targets_observed':len(v),
                'complete_contrasts':pair_counts[name],'missing_contrasts':missing[name],
                'target_complete_contrasts':{target:len(per_target[(name,target)]) for target in v},
                'positive_targets':sum(x>0 for x in v.values()),'negative_targets':sum(x<0 for x in v.values()),
                'unchanged_targets':sum(x==0 for x in v.values())} for name,v in grouped.items()}
 result={'assigned_target_evaluations':len(jobs),'observed_records':len(seen),
         'statuses':dict(Counter(statuses.values())),'pending':len(jobs)-len(seen),
         'effects':effects,'missing_contrasts':dict(missing),'inference':'descriptive; no p-values; targets/prefixes/baselines are shared',
         'baseline_is_gold':False,'scope':'frozen rubric, 12 target texts and two selected history blocks'}

 baseline_groups=defaultdict(list)
 for (target,rep),value in baseline.items():
  if value is not None:baseline_groups[target].append(value)
 result['metric']=metric
 result['baseline_by_target']={target:{'scores':values,'n':len(values),'mean':mean(values),'range':max(values)-min(values)} for target,values in baseline_groups.items()}
 if metric=='total':
  result['dimensions']={k:summarize(plan,observations,metric=k) for k in ('claim_clarity','support_linkage','qualification')}
 return result
