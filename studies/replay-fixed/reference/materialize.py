"""Offline construction of scoring requests from observed, frozen feedback.

Trace checks establish local consistency, not cryptographic proof of provider origin.
No model, SDK, or network calls occur here.
"""
import argparse,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CRITERIA=('claim_clarity','support_linkage','qualification')
class MissingHistory(ValueError):pass

def read(p):return json.loads(Path(p).read_text())
def canonical(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def sha(x):return hashlib.sha256(canonical(x).encode()).hexdigest()
def submission(x):return {k:x[k] for k in ('submission_id','author_id','text')}

def validate_response(x):
 if not isinstance(x,dict) or set(x)!={'scores','reason'}:raise ValueError('response_shape')
 if not isinstance(x['scores'],dict) or set(x['scores'])!=set(CRITERIA):raise ValueError('score_dimensions')
 if any(type(v) is not int or not 0<=v<=4 for v in x['scores'].values()):raise ValueError('score_range')
 if not isinstance(x['reason'],str) or not x['reason'].strip():raise ValueError('reason_missing')
 if len(x['reason'])>300:raise ValueError('reason_too_long')
 return x

def context(root):
 root=Path(root)
 return (read(root/'data/plan.json'),{x['submission_id']:x for x in read(root/'data/history_texts.json')},
         {x['submission_id']:x for x in read(root/'data/target_texts.json')},
         {x['episode_id']:x for x in read(root/'data/episodes.json')},read(root/'data/rubric.json'))

def seed_payload(job,validated,root=ROOT):
 plan,texts,targets,episodes,rubric=context(root)
 jobs={j['job_id']:j for j in plan['seed_jobs']}
 history=[]
 for dep in job['dependencies']:
  if dep not in validated:raise MissingHistory('missing prior seed: '+dep)
  history.append(submission(texts[jobs[dep]['submission_id']])|{'assessment':validated[dep]['response']})
 return {'rubric':rubric,'history':history,'current_submission':submission(texts[job['submission_id']])}

def validate_observations(observations,root=ROOT):
 root=Path(root).resolve();plan,*_=context(root)
 if not isinstance(observations,list):raise ValueError('observations_must_be_list')
 jobs={j['job_id']:j for j in plan['seed_jobs']};by_id={}
 profile=read(root/'data/model-profile.json')
 if sha(profile)!=plan['model_profile_sha256']:raise ValueError('profile_changed')
 for obs in observations:
  jid=obs.get('job_id')
  if jid in by_id or jid not in jobs:raise ValueError('duplicate_or_unknown_seed_job')
  by_id[jid]=obs
 validated={}
 for j in plan['seed_jobs']:
  if j['job_id'] not in by_id:continue
  obs=by_id[j['job_id']];validate_response(obs['response'])
  if obs.get('model_id')!=profile['requested_model'] or obs.get('model_profile_sha256')!=plan['model_profile_sha256']:
   raise ValueError('observed_model_or_profile_mismatch')
  expected=seed_payload(j,validated,root)
  if obs.get('input_sha256')!=sha(expected):raise ValueError('seed_input_mismatch')
  path=(root/obs['trace_path']).resolve()
  if not path.is_relative_to(root/'runs') or not path.is_file():raise ValueError('trace_outside_run_or_missing')
  if hashlib.sha256(path.read_bytes()).hexdigest()!=obs.get('trace_sha256'):raise ValueError('trace_hash_mismatch')
  trace=read(path)
  if trace.get('input')!=expected or trace.get('response')!=obs['response']:raise ValueError('trace_content_mismatch')
  if trace.get('model_id')!=obs['model_id'] or trace.get('model_profile_sha256')!=obs['model_profile_sha256']:
   raise ValueError('trace_model_mismatch')
  if trace.get('status')!='completed':raise ValueError('trace_not_completed')
  validated[j['job_id']]=obs
 return validated

def build_target_payload(job,observations,root=ROOT):
 plan,texts,targets,episodes,rubric=context(root)
 history=[]
 if job['condition']!='single':
  episode=episodes[job['episode_id']]
  if job['condition']=='text_and_feedback':
   verified=validate_observations(observations,root)
   seed_jobs={j['submission_id']:j for j in plan['seed_jobs'] if j['episode_id']==episode['episode_id']}
  for sid in episode['submission_ids']:
   assessment=None
   if job['condition']=='text_and_feedback':
    jid=seed_jobs[sid]['job_id']
    if jid not in verified:raise MissingHistory('feedback not generated: '+jid)
    assessment=verified[jid]['response']
   history.append(submission(texts[sid])|{'assessment':assessment})
 return {'rubric':rubric,'history':history,'current_submission':submission(targets[job['target_id']])}

def main():
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--observations',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
 a=p.parse_args();obs=read(a.observations);verified=validate_observations(obs,a.root)
 plan=read(a.root/'data/plan.json')
 if len(verified)!=96:raise MissingHistory('all 96 observed seed evaluations must be frozen before main replay')
 a.output.mkdir(parents=True,exist_ok=True)
 if any(a.output.iterdir()):raise ValueError('output_must_be_empty')
 for job in plan['target_jobs']:
  payload=build_target_payload(job,obs,a.root)
  (a.output/(job['job_id']+'.json')).write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
 (a.output/'materialization.json').write_text(json.dumps({'status':'inputs_materialized_not_target_results',
  'observed_seed_jobs':96,'target_inputs':624,'observations_sha256':hashlib.sha256(a.observations.read_bytes()).hexdigest(),
  'model_profile_sha256':plan['model_profile_sha256']},indent=2)+'\n')
if __name__=='__main__':main()
