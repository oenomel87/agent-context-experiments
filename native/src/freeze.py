"""Immutable main-only source/data snapshots and per-request mutation guard."""
import hashlib,json,shutil
from pathlib import Path
DATA=('plan.json','session-blueprints.json','stimuli.json','neutral-probe.json','rubric.json','assessment.schema.json')
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def inventory(root):
 root=Path(root).resolve();paths=[root/'data'/x for x in DATA]
 paths += sorted(p for folder in ['src','schemas'] for p in (root/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
 paths += [root/x for x in ['PROTOCOL.md','EXECUTION.md'] if (root/x).exists()]
 sdk=root.parent/'backend'
 paths += [sdk/'src'/x for x in ['sdk_adapter.py','sdk_bridge.mjs','sdk_exec_wrapper.py']]+[sdk/'package-lock.json']
 return {str(p.relative_to(root)) if p.is_relative_to(root) else str(p):digest(p) for p in paths}
def freeze(root,run):
 root,run=Path(root).resolve(),Path(run).resolve()
 import contracts
 ins=contracts.instructions()
 manifest={'files':inventory(root),'scope':'main_four_conditions','planned_calls':1090,'instructions_sha256':hashlib.sha256(ins.encode()).hexdigest()}
 p=run/'run-manifest.json'
 if p.exists():
  if json.loads(p.read_text())!=manifest:raise ValueError('frozen_inputs_changed')
  return manifest
 for rel,h in manifest['files'].items():
  source=Path(rel) if Path(rel).is_absolute() else root/rel
  target=run/'snapshots'/('adapter/'+source.name if Path(rel).is_absolute() else rel)
  target.parent.mkdir(parents=True,exist_ok=True)
  with target.open('xb') as f:f.write(source.read_bytes())
  assert digest(target)==h
 with (run/'instructions.txt').open('x') as f:f.write(ins)
 with p.open('x') as f:json.dump(manifest,f,indent=2);f.write('\n')
 return manifest
def guard(root,run):
 m=json.loads((Path(run)/'run-manifest.json').read_text())
 if m['files']!=inventory(root):raise RuntimeError('frozen_inputs_changed')
