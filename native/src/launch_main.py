"""Preflight-gated native main experiment supervisor. No auxiliary execution."""
import sys,json,subprocess,os,shutil
from pathlib import Path
from datetime import datetime,timezone
from freeze import freeze
ROOT=Path(__file__).resolve().parents[1];RUN=ROOT/'runs/main-20261025-v1';PREFLIGHT=ROOT/'runs/preflight-20261025-v1/preflight-summary.json'
def now():return datetime.now(timezone.utc).isoformat()
def save(c):
 p=RUN/'control.pending.json';p.write_text(json.dumps(c,ensure_ascii=False,indent=2)+'\n');p.replace(RUN/'control.json')
def main():
 RUN.mkdir(parents=True,exist_ok=True)
 if (RUN/'control.json').exists():raise RuntimeError('Existing execution preserved; no automatic native recovery')
 proof=json.loads(PREFLIGHT.read_text());assert proof['status']=='passed' and proof['technical_model_calls']==10
 shutil.copyfile(PREFLIGHT,RUN/'preflight.json');freeze(ROOT,RUN)
 c={'status':'running','scope':'main_four_conditions','planned':1090,'technical_preflight_calls':10,'auxiliary_calls':0,'started_at_utc':now(),'supervisor_pid':os.getpid(),'model':'gpt-6-luna','effort':'medium'};save(c)
 with (RUN/'runner.log').open('x') as log:
  p=subprocess.Popen([sys.executable,'-u',str(ROOT/'src/run_experiment.py'),'--run-dir',str(RUN)],stdout=log,stderr=subprocess.STDOUT)
  c['runner_pid']=p.pid;save(c)
  while True:
   try:code=p.wait(timeout=30);break
   except subprocess.TimeoutExpired:
    c['updated_at_utc']=now()
    if (RUN/'progress.json').exists():c['progress']=json.loads((RUN/'progress.json').read_text())
    save(c);print(json.dumps(c.get('progress',{})),flush=True)
 c.update(status='completed' if code==0 else 'stopped_with_error',exit_code=code,finished_at_utc=now());save(c)
 c['postprocessing']=[]
 for script in ['report_results.py','verify_run.py']:
  r=subprocess.run([sys.executable,str(ROOT/'src'/script),'--run',str(RUN)],capture_output=True,text=True)
  c['postprocessing'].append({'script':script,'exit_code':r.returncode,'stdout':r.stdout,'stderr':r.stderr})
 c['wall_seconds']=(datetime.fromisoformat(c['finished_at_utc'])-datetime.fromisoformat(c['started_at_utc'])).total_seconds()
 if (RUN/'progress.json').exists():c['progress']=json.loads((RUN/'progress.json').read_text())
 save(c);print(json.dumps(c,ensure_ascii=False),flush=True)
 return code or (0 if all(x['exit_code']==0 for x in c['postprocessing']) else 2)
if __name__=='__main__':sys.exit(main())
