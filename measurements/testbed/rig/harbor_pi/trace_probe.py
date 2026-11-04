"""Zero-model check that CLI tracing preserves version stdout/stderr/exit."""
import hashlib
import json
from pathlib import Path
import subprocess

PROGRAMS = {
    'bx': '/opt/study/bin/bx', 'psql': '/usr/lib/postgresql/16/bin/psql',
    'playwright-cli': '/opt/pi/node_modules/.bin/playwright-cli',
    'gh-github': '/opt/study/bin/gh-github',
}
results = []
for name, real in PROGRAMS.items():
    plain = subprocess.run([real, '--version'], capture_output=True)
    traced = subprocess.run(['/opt/traced/bin/' + name, '--version'], capture_output=True)
    assert (plain.returncode, plain.stdout, plain.stderr) == (traced.returncode, traced.stdout, traced.stderr)
    assert plain.returncode == 0
    results.append({'cli': name, 'output_sha256': hashlib.sha256(plain.stdout).hexdigest(),
                    'exit': plain.returncode, 'stdout_stderr_exit_identical': True})
traces = [json.loads(p.read_text()) for p in Path('/logs/agent/cli-traces').glob('*.json')]
assert len(traces) == len(PROGRAMS) and all(t['status'] == 'completed' for t in traces)
print(json.dumps({'model_calls': 0, 'wrapper_semantic_probe': results,
                  'recorded_invocations': len(traces), 'ok': True}, indent=2))
