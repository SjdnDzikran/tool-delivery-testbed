#!/usr/local/bin/python3
"""Transparent CLI stdout capture. Arguments/credentials are never logged."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

PROGRAMS = {
    'bx': '/opt/study/bin/bx',
    'psql': '/usr/lib/postgresql/16/bin/psql',
    'playwright-cli': '/opt/pi/node_modules/.bin/playwright-cli',
    'gh-github': '/opt/study/bin/gh-github',
}
name = Path(sys.argv[0]).name
if name not in PROGRAMS:
    raise SystemExit('Unknown traced CLI')
root = Path('/logs/agent/cli-traces')
root.mkdir(parents=True, exist_ok=True, mode=0o700)
identifier = str(time.time_ns()) + '-' + uuid.uuid4().hex
metadata = root / (identifier + '.json')
allowed = {'web', 'news', 'images', 'videos', 'api', 'pr', 'issue', 'repo',
           'open', 'snapshot', 'click', 'close', 'close-all', 'eval', 'list'}
args = sys.argv[1:]
record = {'program': name, 'argument_sha256': hashlib.sha256(json.dumps(args).encode()).hexdigest(),
          'subcommand': args[0] if args and args[0] in allowed else 'other',
          'argc': len(args), 'status': 'started', 'start_ns': time.time_ns()}
def save():
    fd = os.open(metadata, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as out:
        json.dump(record, out)
        out.write('\n')
save()  # Fail before performing an unrecorded external operation.
fd = os.open(root / (identifier + '.stdout'), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'wb') as trace:
    process = subprocess.Popen([PROGRAMS[name], *args], stdout=subprocess.PIPE)
    assert process.stdout is not None
    while chunk := process.stdout.read1(65536):
        trace.write(chunk)
        sys.stdout.buffer.write(chunk)
        sys.stdout.buffer.flush()
    code = process.wait()
record.update(status='completed', returncode=code, end_ns=time.time_ns())
save()
# Preserve conventional exit semantics when the underlying process is signalled.
sys.exit(code if code >= 0 else 128 - code)
