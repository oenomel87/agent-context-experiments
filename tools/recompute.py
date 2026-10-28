"""Recompute all three published studies offline. Never loads the live backend."""
from pathlib import Path
import importlib.util,json,shutil,sys,tempfile
ROOT=Path(__file__).resolve().parents[1]
def read(p):return json.loads(p.read_text())
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def rows(path):return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
def recompute():
 native=ROOT/'native';obs=rows(native/'published/observations.jsonl')
 with tempfile.TemporaryDirectory() as tmp:
  p=Path(tmp);(p/'snapshots/data').mkdir(parents=True)
  shutil.copyfile(native/'data/plan.json',p/'snapshots/data/plan.json')
  (p/'records.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in obs))
  m=load('published_native_report',native/'src/report_results.py');n=m.report(p)
  native_summary={k:n[k] for k in ['planned_calls','observed_records','statuses','valid_grades','cells','primary','baseline_per_text','contrasts']}
 base=ROOT/'studies/replay-fixed';sys.path.insert(0,str(base/'reference'))
 fixed=load('published_fixed_analysis',base/'reference/analyze.py')
 plan=read(base/'data/plan.json');f=fixed.summarize(plan,[r for r in rows(base/'observations.jsonl') if r['kind']=='target'])
 base=ROOT/'studies/replay-cumulative'
 with tempfile.TemporaryDirectory() as tmp:
  p=Path(tmp);(p/'snapshots/data').mkdir(parents=True);(p/'records').mkdir()
  shutil.copyfile(base/'data/plan.json',p/'snapshots/data/plan.json')
  for r in rows(base/'observations.jsonl'):(p/'records'/(r['job_id']+'.json')).write_text(json.dumps(r,ensure_ascii=False))
  c=load('published_cumulative_report',base/'reference/report_results.py').build_summary(p)
  cumulative={k:c[k] for k in ['planned','counts','valid_scores','baseline','depth','curves','trajectory_summary']}
 return {'native':native_summary,'replay_fixed':f,'replay_cumulative':cumulative}
if __name__=='__main__':
 result=recompute();out=ROOT/'build';out.mkdir(exist_ok=True)
 (out/'recomputed.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'native_primary':{k:{'n':v['n'],'mean_total':v['means']['total'],'mean_absolute_total':v['mean_absolute']['total']} for k,v in result['native']['primary'].items()},'replay_cumulative_probe_delta':{g:result['replay_cumulative']['trajectory_summary'][g]['total']['mean_k1_10']['mean'] for g in ['warm','cool']}},ensure_ascii=False,indent=2))
