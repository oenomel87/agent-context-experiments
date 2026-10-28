#!/usr/bin/env python3
"""Use only exec, discard inherited user config, retain authentication/managed policy."""
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
from codex_cli_bin import bundled_codex_path
cli = Path(bundled_codex_path())
args = sys.argv[1:]
if 'exec' not in args:
    raise SystemExit('SDK wrapper permits only exec')
if '--sandbox' in args or '--dangerously-bypass-approvals-and-sandbox' in args:
    raise SystemExit('Legacy or bypass sandbox options are forbidden')
for name in ('CODEX_APP_TOOLS_PIPE_PATH', 'CODEX_SESSION_ID', 'CODEX_THREAD_ID', 'CODEX_INTERNAL_ORIGINATOR_OVERRIDE'):
    os.environ.pop(name, None)
pos = args.index('exec') + 1
args[pos:pos] = ['--ignore-user-config', '--ignore-rules']
os.execv(str(cli), [str(cli), *args])
