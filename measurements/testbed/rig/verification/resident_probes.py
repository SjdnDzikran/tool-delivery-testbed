#!/usr/bin/env python3
"""Task-free resident-token probes for RQ1. SPENDS MODEL TOKENS when run.

Sends one short prompt under every capability subset, delivery configuration,
model and repetition, using the campaign's own agent-directory and argv code.
An empty-catalog probe is the baseline, so subtracting it removes Pi's base
prompt, native tools and the probe prompt. Each probe runs in a disposable
container that mounts the host's pinned programs at the campaign's paths, so
the paths Pi writes into its system prompt match the campaign.

Usage, from a bash shell with the rig's env.sh and `pgfixture env` applied, with
RUNTIME_DIR naming the rig runtime that holds the pinned programs:
  python3 resident_probes.py OUT_DIR [--filter REGEX] [--reps N]
Completed cells in OUT_DIR/rows.jsonl are never repeated.
"""
import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import random
import re
import shlex
import shutil
import subprocess
import sys
import tomllib

RIG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RIG))
import runner  # noqa: E402

MANIFEST = RIG / 'examples/harbor-campaign.toml'
OBSERVER = RIG / 'verification/observer/pi-request-observer.ts'
PI = Path.home() / '.pi/research/node_modules/.bin/pi'
AUTH = Path.home() / '.pi/research/agent/auth.json'
PROMPT = 'Reply with exactly: OK. Do not call any tools.'
SEED = 2026
TIMEOUT_S = 240
IMAGE = 'node:24-bookworm-slim@sha256:c86ecead9e55a5210ac1727de38a4ca840bf03dcaf34dc9749addbf383b1920c'
WORK, AGENT, LOGS = '/home/study/workspace', '/home/study/.pi-experiment', '/logs/agent'
PG_READY = '/usr/lib/postgresql/16/bin/pg_isready'
NATIVE_TOOLS = 4
PAIRS = {'brave-search': 'bx', 'playwright': 'playwright-cli', 'postgres': 'psql', 'github': 'gh'}
TOOLS = {'brave-search': 8, 'playwright': 25, 'postgres': 9, 'github': 46}
MODES = ('eager', 'deferred', 'cli')


def load_manifest():
    m = tomllib.loads(MANIFEST.read_text())
    m['harness'].update(binary=str(PI), auth_source=str(AUTH), auth_mode='symlink')
    m['paths']['skills_dir'] = str(RIG / 'skills')
    m['catalog']['postgres']['env'] = {'DATABASE_URI': os.environ['TESTBED_PG_DSN']}
    return m


def plan(models, reps):
    subsets = [c for n in range(len(PAIRS) + 1) for c in itertools.combinations(sorted(PAIRS), n)]
    cells = [{'model': model, 'mode': mode, 'subset': list(subset), 'rep': rep}
             for model in models for mode in MODES for subset in subsets
             for rep in range(1, reps + 1)]
    random.Random(SEED).shuffle(cells)
    for order, cell in enumerate(cells, 1):
        cell['order'] = order
        cell['id'] = '-'.join((cell['model'], cell['mode'],
                               '+'.join(cell['subset']) or 'empty', f"r{cell['rep']}"))
    return cells


def tool_name(tool):
    return tool.get('name') or tool.get('function', {}).get('name')


def tools_match(cell, payload):
    """Every assigned server tool is present, and no other server's tool is."""
    names = [tool_name(t) for t in payload.get('tools') or []]
    served = {}
    for name in names:
        if name.startswith('mcp__'):
            server = name.split('__')[1].replace('_', '-')
            served[server] = served.get(server, 0) + 1
    if cell['mode'] != 'eager':
        expected_count = NATIVE_TOOLS + (cell['mode'] == 'deferred' and bool(cell['subset']))
        return not served and len(names) == expected_count
    return served == {s: TOOLS[s] for s in cell['subset']}


def canonical_tools(payload):
    tools = sorted(payload.get('tools') or [],
                   key=tool_name)
    return json.dumps(tools, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def run_cell(m, cell, out):
    directory = out / 'cells' / cell['id']
    directory.mkdir(parents=True)
    logs = directory / 'logs'
    (directory / 'work').mkdir()
    logs.mkdir()
    task = {'catalog': cell['subset'], 'capabilities': [PAIRS[s] for s in cell['subset']]}
    manifest = {**m, 'tasks': {'probe': task}}
    spec = {'task': 'probe', 'mode': cell['mode'], 'model': cell['model'], 'catalog': 'required'}
    agent = runner.prepare_agent_dir(manifest, spec, {}, directory)['agent_dir']
    manifest['harness'] = {**m['harness'], 'binary': '/opt/pi/node_modules/.bin/pi'}
    argv = runner.build_argv(manifest, spec, PROMPT, Path(AGENT), Path(LOGS) / 'sessions')
    argv[-2:-2] = ['-e', '/opt/study/observer.ts']
    runtime = Path(os.environ['RUNTIME_DIR'])
    node = Path(shutil.which('node')).resolve()
    mounts = [('/usr', '/usr', 'ro'), ('/etc/ssl', '/etc/ssl', 'ro'), ('/etc/passwd', '/etc/passwd', 'ro'),
              (node.parent, '/opt/node/bin', 'ro'), (runtime, runtime, 'ro'),
              (PI.parents[2], PI.parents[2], 'ro'), (AUTH.parent, AUTH.parent, 'rw'),
              (PI.parents[1], '/opt/pi/node_modules', 'ro'), (OBSERVER, '/opt/study/observer.ts', 'ro'),
              (agent, AGENT, 'rw'), (directory / 'work', WORK, 'rw'), (logs, LOGS, 'rw')]
    env = {'HOME': '/home/study', 'USER': 'study', 'LOGNAME': 'study', 'LANG': 'C.UTF-8',
           'PATH': f'{runtime}/bin:/opt/pi/node_modules/.bin:/opt/node/bin:/usr/bin:/bin',
           'PI_CODING_AGENT_DIR': AGENT, 'PI_SKIP_VERSION_CHECK': '1', 'PI_OFFLINE': '1',
           'PI_OBSERVER_DIR': f'{LOGS}/requests', 'PI_OBSERVER_RAW_DIR': f'{LOGS}/raw-requests'}
    name = 'resident-probe-' + hashlib.sha256(str(directory).encode()).hexdigest()[:12]
    docker = ['docker', 'run', '--rm', '--name', name, '--network', 'host', '--user', f'{os.getuid()}:{os.getgid()}',
              '--tmpfs', f'/home/study:uid={os.getuid()},gid={os.getgid()}', '--workdir', WORK]
    for source, target, access in mounts:
        docker += ['-v', f'{source}:{target}:{access}']
    for key, value in env.items():
        docker += ['-e', f'{key}={value}']
    docker += ['-e', 'BRAVE_API_KEY', '-e', 'STUDY_GITHUB_TOKEN', '--entrypoint', '/opt/node/bin/node', IMAGE]
    command = docker + [argv[0], *argv[1:]]
    row = {k: cell[k] for k in ('id', 'order', 'model', 'mode', 'subset', 'rep')}
    with open(logs / 'events.jsonl', 'w') as events, open(logs / 'stderr.txt', 'w') as err:
        try:
            row['exit_code'] = subprocess.run(['sg', 'docker', '-c', shlex.join(command)], stdout=events, stderr=err,
                                              stdin=subprocess.DEVNULL, timeout=TIMEOUT_S).returncode
        except subprocess.TimeoutExpired:
            row['exit_code'] = 'timeout'
            subprocess.run(['sg', 'docker', '-c', f'docker rm -f {name}'], capture_output=True)
    assistant = []
    for line in (logs / 'events.jsonl').read_text(errors='replace').splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('type') == 'message_end' and event.get('message', {}).get('role') == 'assistant':
            assistant.append(event['message'])
    requests = sorted((logs / 'raw-requests').glob('*.json'))
    row['assistant_messages'] = len(assistant)
    row['requests'] = len(requests)
    if assistant:
        usage = assistant[0].get('usage') or {}
        row['usage'] = {k: usage.get(k, 0) for k in ('input', 'output', 'cacheRead', 'cacheWrite')}
        row['first_request_input_tokens'] = sum(usage.get(k, 0) for k in ('input', 'cacheRead', 'cacheWrite'))
        row['stop_reason'] = assistant[0].get('stopReason')
    if requests:
        payload = json.loads(requests[0].read_text())
        row['tool_count'] = len(payload.get('tools') or [])
        row['tools_sha256'] = hashlib.sha256(canonical_tools(payload).encode()).hexdigest()
        row['tools_valid'] = tools_match(cell, payload)
        row['extra_tools'] = [n for n in map(tool_name, payload.get('tools') or []) if not n.startswith('mcp__')][NATIVE_TOOLS:]
    row['valid'] = (row['exit_code'] == 0 and row['assistant_messages'] == 1 and row['requests'] == 1
                    and row.get('stop_reason') == 'stop' and row.get('tools_valid', False))
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out', type=Path)
    parser.add_argument('--filter', default='.')
    parser.add_argument('--reps', type=int, default=3)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    rows_path = args.out / 'rows.jsonl'
    done = set()
    if rows_path.exists():
        done = {json.loads(line)['id'] for line in rows_path.read_text().splitlines()}
    m = load_manifest()
    cells = [c for c in plan(sorted(m['models']), args.reps)
             if re.search(args.filter, c['id']) and c['id'] not in done]
    failures = 0
    for index, cell in enumerate(cells, 1):
        subprocess.run([PG_READY, '-h', '127.0.0.1', '-p', '55432', '-q'], check=True)
        row = run_cell(m, cell, args.out)
        with open(rows_path, 'a') as handle:
            handle.write(json.dumps(row) + '\n')
        print(index, len(cells), row['id'], row.get('first_request_input_tokens'),
              row.get('tool_count'), 'ok' if row['valid'] else 'INVALID', flush=True)
        failures = 0 if row['valid'] else failures + 1
        if failures >= 3:
            raise SystemExit('Stopping after three consecutive invalid probes')


if __name__ == '__main__':
    main()
