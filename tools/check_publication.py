"""Check the public copy for disallowed artifacts and credential-like strings; print no values."""
from pathlib import Path
import json,re,sys,hashlib
ROOT=Path(__file__).resolve().parents[1]
FORBIDDEN_DIRS={'node_modules','.venv','.codex','runs','traces','native-evidence','snapshots'}
PATTERNS={
 'private_home_path':re.compile(r'/(?:Users|home)/[A-Za-z0-9_.-]+/'),
 'provider_uuid':re.compile(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b'),
 'api_key_like':re.compile(r'\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{25,}'),
 'github_token_like':re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{30,})'),
 'private_key_pem':re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
 'jwt_like':re.compile(r'\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}'),
 'bearer_value_like':re.compile(r'(?i)Bearer\s+[A-Za-z0-9_.-]{24,}')}
def check():
 errors=[];files=0
 for p in ROOT.rglob('*'):
  rel=p.relative_to(ROOT)
  if any(x in {'.git','__pycache__','build'} for x in rel.parts):continue
  if p.is_symlink():errors.append({'path':str(rel),'issue':'symlink'});continue
  if p.is_dir():
   if p.name in FORBIDDEN_DIRS:errors.append({'path':str(rel),'issue':'runtime_directory'})
   continue
  files+=1
  if p.name in {'auth.json','credentials.json'} or p.name.startswith('.env') and p.name!='.env.example':errors.append({'path':str(rel),'issue':'credential_filename'})
  try:text=p.read_text()
  except UnicodeError:continue
  for name,pattern in PATTERNS.items():
   if pattern.search(text):errors.append({'path':str(rel),'issue':name})
 manifest=ROOT/'PUBLICATION_MANIFEST.json'
 if manifest.exists():
  expected=json.loads(manifest.read_text())['files']
  actual={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.rglob('*') if p.is_file() and not any(x in {'.git','__pycache__','build'} for x in p.relative_to(ROOT).parts) and str(p.relative_to(ROOT)) not in {'PUBLICATION_MANIFEST.json','docs/PUBLICATION_CHECK.json'}}
  for path in sorted(set(expected)|set(actual)):
   if expected.get(path)!=actual.get(path):errors.append({'path':path,'issue':'manifest_mismatch'})
 return {'status':'passed' if not errors else 'failed','files_checked':files,'issues':errors,'scope':'Static public-copy checks only; no legal clearance or proof that every possible secret is absent.'}
if __name__=='__main__':
 result=check();print(json.dumps(result,ensure_ascii=False,indent=2));sys.exit(0 if result['status']=='passed' else 1)
