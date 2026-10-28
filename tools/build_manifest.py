"""Record the exact publication file inventory; not a provider execution attestation."""
import json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
files={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ROOT.rglob('*')) if p.is_file() and not any(x in {'.git','__pycache__','build'} for x in p.relative_to(ROOT).parts) and str(p.relative_to(ROOT)) not in {'PUBLICATION_MANIFEST.json','docs/PUBLICATION_CHECK.json'}}
manifest={'edition':'v4-corrected-dialogue-coordinator-and-full-evaluator','unique_design_assignments':1970,'unique_valid_evaluations':1078,'canonical_completed':1930,'canonical_failed':6,'canonical_blocked':34,'reused_baselines':210,'legacy_publication_preserved_in_git_history':'eba5cc3addd1e75aa8265d0155cd0800c74823c5','files':files}
(ROOT/'PUBLICATION_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n');print(f'Manifest: {len(files)} content files')
