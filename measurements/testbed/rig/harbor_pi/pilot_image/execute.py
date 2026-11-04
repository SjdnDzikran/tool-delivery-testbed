"""One Pi invocation with the existing bounded watchdog; no retry/orchestration."""
import json
import os
from pathlib import Path
import sys
from runner import PiRun

run = PiRun(sys.argv[1:], Path.cwd(), dict(os.environ),
            Path('/logs/agent/events.jsonl'), Path('/logs/agent/stderr.txt'),
            deadline_s=int(os.environ.get('PI_TRIAL_DEADLINE_S', '590')),
            budget_tokens=int(os.environ.get('PI_TRIAL_BUDGET_TOKENS', '250000')))
run.execute()
status, detail = run.classify_stop()
Path('/logs/agent/process.json').write_text(json.dumps({
    'status': status, 'detail': detail, 'returncode': run.returncode,
    'killed_reason': run.killed_reason, 'parse_errors': run.parse_errors,
    'watchdog_scope': 'assistant-message usage, not complete billed cost',
}) + '\n')
sys.exit(0 if status == 'verify' else 1)
