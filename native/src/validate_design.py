"""Offline checks of primary scope, native sessions and role visibility."""
import json,hashlib,re
from pathlib import Path
from collections import Counter
R=Path(__file__).resolve().parents[1]
def read(p):return json.loads((R/p).read_text())
def check():
 p=read('data/plan.json');j={x['job_id']:x for x in p['jobs']};ss=read('data/session-blueprints.json')
 assert p['scope']=='main_four_conditions' and len(j)==1090 and len(ss)==470
 assert set(x['arm'] for x in j.values())=={'I','S2','M2'}
 assert len({x['job_id'] for x in p['jobs']})==len(p['jobs'])
 assert sum(x['stage']=='analyze' for x in j.values())==440
 assert sum(x['stage']!='analyze' for x in j.values())==650
 for arm,tone in [('S2','warm'),('S2','cool'),('M2','warm'),('M2','cool')]:
  rows=[x for x in j.values() if x['arm']==arm and x['tone']==tone]
  assert len(rows)==220
  assert Counter(x['stage'] for x in rows)=={'analyze':110,'judge':100,'probe':10}
  sessions=[x for x in ss if x['arm']==arm and x['tone']==tone]
  assert Counter(x['turn_count'] for x in sessions)==({22:10} if arm=='S2' else {11:10,1:110})
 for s in ss:
  rows=[j[x] for x in s['ordered_jobs']]
  assert [x['session_turn'] for x in rows]==list(range(1,len(rows)+1))
  for prev,cur in zip(rows,rows[1:]):assert prev['job_id'] in cur['requires']
  probes=[x for x in rows if x['stage']=='probe']
  assert not probes or probes[-1]==rows[-1]
 for x in j.values():
  assert set(x['requires'])<=set(j)
  if x['arm']=='M2':
   assert x['prior_judgment_jobs']==[]
   if x['stage']=='analyze':assert all(j[y]['stage']=='analyze' for y in x['requires'])
   else:
    assert x['session_turn']==1 and x['requires']==[x['analysis_job_id']]
    assert j[x['analysis_job_id']]['submission_id']==x['submission_id']
 baseline=[x for x in j.values() if x['arm']=='I']
 assert len(baseline)==210 and set(Counter(x['submission_id'] for x in baseline).values())=={10}
 for file,n in [('data/auxiliary-plan.json',900),('data/auxiliary-standalone-plan.json',1110),('data/combined-plan.json',1990)]:
  q=read(file);ids={x['job_id'] for x in q['jobs']};assert len(ids)==n
  done=set()
  for jid in q['launch_priority']:
   x=next(x for x in q['jobs'] if x['job_id']==jid)
   assert set(x['requires'])<=done;done.add(jid)
  assert done==ids
 assert len(read('data/auxiliary-plan.json')['external_baseline_job_ids'])==210
 assert read('data/auxiliary-standalone-plan.json')['external_baseline_job_ids']==[]
 for name in ['README.md','PROTOCOL.md','AUXILIARY.md','review/turn-flow.md']:
  path=R/name
  for url in re.findall(r'\]\(([^)]+)\)',path.read_text()):
   if not url.startswith('http'):assert (path.parent/url).exists(),url
 out=read('validation.json');out.update(primary_boundary_checked=True,main_four_cells_balanced=True,multi_judgments_never_feed_analyst=True,common_baselines_once=True,all_launch_orders_topological=True,all_sessions_native_turn_order_checked=True)
 (R/'validation.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
 files=[p for p in R.rglob('*') if p.is_file() and '__pycache__' not in p.parts and 'archive' not in p.parts and p.name!='manifest.json']
 (R/'manifest.json').write_text(json.dumps({str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)},indent=2)+'\n')
 print(json.dumps(out,ensure_ascii=False))
if __name__=='__main__':check()
