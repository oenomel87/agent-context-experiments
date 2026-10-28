"""Recompute all published v4 results using only the Python standard library; no model calls."""
import json,statistics,collections
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def rows(path):return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]
def stats(v):
 v=list(v);return {'n':len(v),'mean':statistics.mean(v) if v else None,'sd':statistics.stdev(v) if len(v)>1 else None,'mean_absolute':statistics.mean(abs(x) for x in v) if v else None,'frequencies':dict(sorted(collections.Counter(v).items()))}
def total(r):return sum(r['response']['scores'][k] for k in ['claim_clarity','support_linkage','qualification'])
def summarize(data):
 ev=[r for r in data if r['stage']=='evaluate' and r['status']=='completed'];base={(r['replicate'],r['submission_id']):total(r) for r in ev if r['arm']=='I'};delivered={r['evaluation_job_id'] for r in data if r['stage']=='deliver' and r['status']=='completed'};seqs=sorted({r['sequence'] for r in ev if r['arm']!='I'},reverse=True);cells={};probes={};endtoend={}
 for arm in ['S','M']:
  for seq in seqs:
   rr=[r for r in ev if r['arm']==arm and r['sequence']==seq];cur=[r for r in rr if not r['is_probe']];probe=[r for r in rr if r['is_probe']];delta=lambda r:total(r)-base[r['replicate'],r['submission_id']];k=arm+'_'+seq
   probes[k]={r['replicate']:total(r) for r in probe};endtoend[k]={r['replicate']:total(r) for r in probe if arm=='S' or r['job_id'] in delivered}
   cells[k]={'neutral':stats(total(r) for r in probe),'neutral_delta':stats(delta(r) for r in probe),'neutral_delivered':stats(endtoend[k].values()),'current_delta':stats(delta(r) for r in cur),'current_delta_by_tone':{t:stats(delta(r) for r in cur if r['input_tone']==t) for t in ['warm','cool']},'position_delta':{str(i):stats(delta(r) for r in cur if r['position']==i) for i in range(1,11)}}
 def contrasts(maps):
  result={};common=set.intersection(*(set(v) for v in maps.values()))
  for arm in ['S','M']:
   a,b=maps[arm+'_'+seqs[0]],maps[arm+'_'+seqs[1]];pairs={i:a[i]-b[i] for i in sorted(a.keys()&b.keys())};result[arm]={'per_replicate':pairs,'stats':stats(pairs.values()),'common_stats':stats(pairs[i] for i in common)}
  pairs={i:result['S']['per_replicate'][i]-result['M']['per_replicate'][i] for i in sorted(common)};result['D']={'per_replicate':pairs,'stats':stats(pairs.values())};result['common_replicates']=sorted(common);return result
 new=[r for r in data if r['arm']!='I'];usage=collections.defaultdict(collections.Counter);pooled={}
 for r in data:
  if r['status']=='blocked':continue
  u=usage[r['arm']+'/'+r['role']];u['attempts']+=1
  if r.get('usage') is not None:u.update(r['usage']);u['known_usage_attempts']+=1
  else:u['unknown_usage_attempts']+=1
 for arm in ['S','M']:
  for tone in ['warm','cool']:pooled[arm+'_'+tone]=stats(total(r)-base[r['replicate'],r['submission_id']] for r in ev if r['arm']==arm and not r['is_probe'] and r['input_tone']==tone)
 probeid=json.loads((ROOT/'experiments/homogeneous/data/neutral-probe.json').read_text())['submission_id']
 return {'cells':cells,'neutral_baseline':stats(total(r) for r in ev if r['arm']=='I' and r['submission_id']==probeid),'probe_scores':probes,'contrasts':contrasts(probes),'delivered_contrasts':contrasts(endtoend),'pooled_current_delta_by_tone':pooled,'statuses_including_baselines':dict(collections.Counter(r['status'] for r in data)),'statuses_excluding_baselines':dict(collections.Counter(r['status'] for r in new)),'valid_evaluations_including_baselines':len(ev),'valid_evaluations_excluding_baselines':sum(r['arm']!='I' for r in ev),'delivered':len(delivered),'usage_by_role':dict(usage),'flagged_responses':sum(bool(r.get('flags')) for r in ev),'flagged_quotes':sum(len(r.get('flags',[])) for r in ev)}
def recompute(output=None):
 h=rows(ROOT/'experiments/homogeneous/observations.jsonl');a=rows(ROOT/'experiments/alternating/observations.jsonl');baseline=[r for r in h if r['arm']=='I']
 assert len(h)==1090 and len(a)==880 and len(baseline)==210
 assert not ({r['job_id'] for r in h}&{r['job_id'] for r in a})
 result={'homogeneous':summarize(h),'alternating':summarize(baseline+a),'unique_design_assignments':len(h)+len(a),'unique_valid_evaluations':sum(r['stage']=='evaluate' and r['status']=='completed' for r in h+a),'canonical_statuses':dict(collections.Counter(r['status'] for r in h+a)),'baseline_note':'210 observations reused; counted once in pooled totals. No live calls.'}
 if output:
  p=Path(output);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 return result
if __name__=='__main__':
 r=recompute(ROOT/'build/recomputed-summary.json');print(json.dumps({k:r[k] for k in ['unique_design_assignments','unique_valid_evaluations','canonical_statuses']},ensure_ascii=False));print('Wrote build/recomputed-summary.json; no model calls.')
