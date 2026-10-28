"""Freeze only the authorized homogeneous primary experiment; no prior scores."""
import hashlib,json
from pathlib import Path
DATA=('plan.json','plan-sessions.json','stimuli.json','neutral-probe.json','rubric.json')
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def inventory(root):
 root=Path(root).resolve();ps=[root/'data'/x for x in DATA]
 ps += sorted(p for d in ['src','schemas'] for p in (root/d).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
 ps += [root/x for x in ['PROTOCOL.md','EXECUTION.md']]
 sdk=root.parent.parent/'backend';ps += [sdk/'src'/x for x in ['sdk_adapter.py','sdk_bridge.mjs','sdk_exec_wrapper.py']]+[sdk/'package-lock.json']
 return {str(p.relative_to(root)) if p.is_relative_to(root) else str(p):digest(p) for p in ps}
def freeze(root,run):
 import contracts
 root,run=Path(root).resolve(),Path(run).resolve();ins={role:contracts.instructions(role) for role in ['coordinator','evaluator']}
 manifest={'files':inventory(root),'scope':'homogeneous_primary','planned_calls':1090,'instructions_sha256':{k:hashlib.sha256(v.encode()).hexdigest() for k,v in ins.items()}}
 p=run/'run-manifest.json'
 if p.exists():assert json.loads(p.read_text())==manifest;return manifest
 for rel,h in manifest['files'].items():
  src=Path(rel) if Path(rel).is_absolute() else root/rel;dst=run/'snapshots'/('adapter/'+src.name if Path(rel).is_absolute() else rel);dst.parent.mkdir(parents=True,exist_ok=True)
  with dst.open('xb') as f:f.write(src.read_bytes())
  assert digest(dst)==h
 for role,text in ins.items():
  with (run/f'instructions-{role}.txt').open('x') as f:f.write(text)
 with p.open('x') as f:json.dump(manifest,f,indent=2);f.write('\n')
 return manifest
def guard(root,run):
 if json.loads((Path(run)/'run-manifest.json').read_text())['files']!=inventory(root):raise RuntimeError('frozen_inputs_changed')
