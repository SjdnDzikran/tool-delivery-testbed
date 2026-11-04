"""Harbor engineering matrix. One attempt per cell; failed cells are retained.

Harbor is the only container/trial execution owner. This outer controller only
prepares jobs, checkpoints results and stops pending work on provider/budget errors.
"""
from __future__ import annotations
import argparse
import hashlib
import fcntl
import itertools
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time

from harbor.models.job.config import JobConfig
from harbor.models.task.task import Task
import runner
from harbor_pi.adapter import checked_spec, cell_id, cell_limits
from harbor_pi.bridge import RIG, TESTBED, docker_env, docker_ready
from harbor_pi.pilot_support import TASKS, private_env, session_usage

MANIFEST = RIG / 'examples/harbor-pilot-corrected.toml'
MIN_FREE_BYTES = 3 * (1 << 30)


def sweep_trial_leftovers(output):
    """Disabled: a project-name pattern proves neither ownership nor evidence capture."""
    raise RuntimeError('Automatic leftover sweeping disabled; use evidence-checked owned cleanup')


def prepare_task(manifest_path, output, spec, oracle=False):
    m = runner.load_manifest(manifest_path)
    checked_spec(m, **spec)
    task_name = spec['task']
    if m['harness'].get('harbor_actual_tasks'):
        from harbor_pi.actual_tasks import TASKS as actual_tasks, prepare_task as prepare_actual
        if task_name in actual_tasks:
            return prepare_actual(manifest_path, output, spec, oracle=oracle)
    challenge = bool(m['harness'].get('harbor_skill_challenges'))
    if challenge and (spec['mode'] != 'cli' or not task_name.startswith('cap_')):
        raise ValueError('Skill challenges support CLI capability fixtures only')
    if oracle and not task_name.startswith('control_'):
        raise ValueError('Oracle is only defined for self-contained controls')
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    task = output / 'task'
    env = task / 'environment'
    env.mkdir(parents=True)
    policy = env / 'seccomp.json'
    shutil.copyfile(RIG / 'harbor_pi/pilot_image/seccomp.json', policy)
    (env / 'docker-compose.yaml').write_text(json.dumps({'services': {'main': {
        'security_opt': [f'seccomp={policy}'], 'shm_size': '256m',
    }}}, indent=2) + '\n')
    shutil.copyfile(m['tasks'][task_name]['instruction'], task / 'instruction.md')
    tests = task / 'tests'
    tests.mkdir()
    (tests / 'Dockerfile').write_text('FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337\nCOPY . /tests\nRUN mkdir -p /opt/study\nWORKDIR /home/study/workspace\n')
    if task_name.startswith('control_'):
        directory = {'control_1': 'control_1_filter_sort', 'control_2': 'control_2_group_aggregate'}[task_name]
        source = TESTBED / 'controls' / directory
        target = tests / 'testbed/controls' / directory
        for relative in ('verify.py', 'expected/result.json', 'fixtures/records.json'):
            path = target / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / relative, path)
        common = tests / 'testbed/common'
        common.mkdir(parents=True)
        shutil.copyfile(TESTBED / 'common/verify_lib.py', common / 'verify_lib.py')
        verifier = f'python3 /tests/testbed/controls/{directory}/verify.py --artifacts /home/study/workspace'
        solution = task / 'solution'
        solution.mkdir()
        shutil.copyfile(source / 'expected/result.json', solution / 'result.json')
        (solution / 'solve.sh').write_text('#!/bin/sh\nset -eu\nmkdir -p /home/study/workspace\ncp /solution/result.json /home/study/workspace/result.json\n')
        artifact_paths = ['/home/study/workspace/result.json']
    else:
        source = 'skill_challenge_verify.py' if challenge else 'pilot_verify.py'
        shutil.copyfile(RIG / 'harbor_pi' / source, tests / 'verify.py')
        verifier = f'python3 /tests/verify.py {task_name} /home/study/workspace/artifacts'
        artifact_paths = ['/home/study/workspace/artifacts']
    (tests / 'test.sh').write_text('#!/bin/sh\nset -u\nrm -f /logs/verifier/reward.txt /logs/verifier/reward.json\n' + verifier + '''
rc=$?
printf '%s\\n' "$rc" > /logs/verifier/original-exit-code.txt
case "$rc" in
  0) printf '1\\n' > /logs/verifier/reward.txt ;;
  1|2|3) printf '0\\n' > /logs/verifier/reward.txt ;;
  *) exit "$rc" ;;
esac
''')
    config_text = '''version = "1.0"
[agent]
timeout_sec = LIMIT_DEADLINE
user = "study"
[environment]
cpus = 2
memory_mb = 4096
build_timeout_sec = 900
'''
    config_text = config_text.replace('LIMIT_DEADLINE', str(cell_limits(m, spec)['deadline_s']))
    config_text += 'docker_image = ' + json.dumps(m['harness']['harbor_pilot_image']) + '\n'
    config_text += '''[verifier]
timeout_sec = 120
user = "root"
environment_mode = "separate"
[verifier.environment]
cpus = 1
memory_mb = 512
build_timeout_sec = 900
'''
    if task_name == 'cap_db':
        query = 'SELECT coalesce(json_agg(t),\'[]\'::json) FROM (SELECT id,label FROM smoke_items ORDER BY id) t'
        command = ('/usr/lib/postgresql/16/bin/psql -X -h 127.0.0.1 -U study -d study -Atqc '
                   + shlex.quote(query) + ' > /home/study/db-state.json 2>/logs/agent/db-snapshot-stderr.txt'
                   + ' || printf \'{"snapshot_error":true}\\n\' > /home/study/db-state.json')
        config_text += '[[verifier.collect]]\nuser = "study"\ncommand = ' + json.dumps(command) + '\n'
        artifact_paths.append('/home/study/db-state.json')
        if challenge:
            script = ('CREATE TEMP TABLE roundtrip_check(id integer PRIMARY KEY,label text);\n'
                      "\\copy roundtrip_check FROM '/home/study/workspace/artifacts/roundtrip.csv' WITH (FORMAT csv,HEADER true)\n"
                      "SELECT coalesce(json_agg(t),'[]'::json) FROM (SELECT id,label FROM roundtrip_check ORDER BY id) t;\n")
            command = ('printf %s ' + shlex.quote(script)
                       + ' | /usr/lib/postgresql/16/bin/psql -X -w -qAt -v ON_ERROR_STOP=1 -h 127.0.0.1 -U study -d study'
                       + ' > /home/study/db-csv-roundtrip.json 2>/logs/agent/db-csv-roundtrip-stderr.txt'
                       + ' || printf \'{"snapshot_error":true}\\n\' > /home/study/db-csv-roundtrip.json')
            config_text += '[[verifier.collect]]\nuser = "study"\ncommand = ' + json.dumps(command) + '\n'
            artifact_paths.append('/home/study/db-csv-roundtrip.json')
    if challenge:
        artifact_paths.append('/logs/agent/cli-traces')
        if task_name == 'cap_browser':
            command = ('cd /home/study/workspace && HOME=/home/study '
                       '/opt/pi/node_modules/.bin/playwright-cli --json list '
                       '> /home/study/browser-sessions.json')
            config_text += '[[verifier.collect]]\nuser = "study"\ncommand = ' + json.dumps(command) + '\n'
            artifact_paths.append('/home/study/browser-sessions.json')
    if task_name == 'cap_brave' and not challenge:
        artifact_paths.append('/opt/study/brave-provenance.json')
    for path in artifact_paths:
        config_text += '\n[[artifacts]]\nsource = ' + json.dumps(path) + '\ndestination = ' + json.dumps(Path(path).name) + '\n'
    (task / 'task.toml').write_text(config_text)
    selected = m['models'][spec['model']]
    agent = {'name': 'oracle'} if oracle else {
        'import_path': 'harbor_pi.adapter:PiAgent',
        'model_name': f"{selected['provider']}/{selected['id']}",
        'kwargs': {'manifest_path': str(manifest_path.resolve()),
                   'manifest_digest': runner.sha256_json(m), **spec},
    }
    verifier_sink = output / 'agent-verifier-empty'
    verifier_sink.mkdir()
    config = {'job_name': cell_id(spec) + ('-oracle' if oracle else ''),
              'jobs_dir': str(output / 'jobs'), 'n_attempts': 1,
              'n_concurrent_trials': 1, 'retry': {'max_retries': 0},
              'environment': {'type': 'docker', 'delete': True, 'mounts': [{
                  'type': 'bind', 'source': str(verifier_sink),
                  'target': '/logs/verifier', 'read_only': True,
              }]}, 'agents': [agent],
              'tasks': [{'path': str(task)}]}
    JobConfig.model_validate(config)
    Task(task)
    path = output / 'job.json'
    path.write_text(json.dumps(config, indent=2) + '\n')
    (output / 'scope.json').write_text(json.dumps({
        'spec': spec, 'limits': cell_limits(m, spec), 'engineering_only': True, 'execution_owner': 'Harbor 0.23.0',
        'trace_cli': bool(m['harness'].get('harbor_trace_cli')),
        'route_contract': m['harness'].get('harbor_route_contract'),
        'automatic_retries': 0, 'image_id': m['harness']['harbor_image_id'],
        'chrome_sandbox': 'enabled; published Playwright seccomp policy, no extra capabilities',
        'policy_sha256': hashlib.sha256(policy.read_bytes()).hexdigest(),
    }, indent=2) + '\n')
    return path


def result_summary(directory):
    scope = json.loads((directory / 'scope.json').read_text())
    row = {**scope['spec'], 'attempt_dir': str(directory.relative_to(RIG)),
           'verifier_pass': False, 'status': 'not_completed', 'total_tokens': 0,
           'route_status': 'not_audited', 'outcome': 'not_completed',
           'limits': scope.get('limits')}
    files = list((directory / 'jobs').glob('*/task*/result.json'))
    if not files:
        configs = list((directory / 'jobs').glob('*/task*/config.json'))
        if not configs:
            return row
        tfile = configs[0].with_name('result.json')
        trial = {'exception_info': {'exception_type': 'InterruptedController'}}
    else:
        tfile = files[0]
        trial = json.loads(tfile.read_text())
    exception = trial.get('exception_info') or {}
    rewards = (trial.get('verifier_result') or {}).get('rewards') or {}
    row['verifier_reward_present'] = 'reward' in rewards
    row.update(status=exception.get('exception_type', 'completed'),
               verifier_pass=rewards.get('reward') == 1,
               exception_type=exception.get('exception_type'))
    agent = tfile.parent / 'agent'
    ledger = agent / 'session-usage.json'
    if ledger.is_file() or (agent / 'sessions').exists():
        u = json.loads(ledger.read_text()) if ledger.is_file() else session_usage(agent / 'sessions')
        row.update({k: u[k] for k in ('total_tokens', 'input_tokens', 'output_tokens', 'cache_read_tokens', 'ledger_has_no_missing_usage')})
        row['usage_categories'] = sorted({r['category'] for r in u['records']})
    events_file = agent / 'events.jsonl'
    events = [json.loads(s) for s in events_file.read_text().split('\n') if s.strip()] if events_file.is_file() else []
    messages = [e['message'] for e in events if e.get('type') == 'message_end']
    calls = [b for m in messages if m.get('role') == 'assistant' for b in m.get('content', []) if isinstance(b, dict) and b.get('type') == 'toolCall']
    row['tool_call_count'] = len(calls)
    row['tool_names'] = sorted({b['name'] for b in calls})
    row['turns'] = sum(m.get('role') == 'assistant' for m in messages)
    row['provider_error'] = any(m.get('stopReason') == 'error' for m in messages)
    process = agent / 'process.json'
    if process.is_file():
        process_info = json.loads(process.read_text())
        row['process_status'] = process_info.get('status')
        row['stopping_reason'] = process_info.get('killed_reason')
    if messages:
        usage = next((m.get('usage') for m in messages if m.get('role') == 'assistant' and m.get('usage')), {})
        row['first_request_input_tokens'] = sum(usage.get(k, 0) for k in ('input', 'cacheRead', 'cacheWrite'))
    requests = sorted((agent / 'raw-requests').glob('*.json'))
    row['observed_requests'] = len(requests)
    if requests:
        first = json.loads(requests[0].read_text())
        tools = first.get('tools', [])
        row['initial_tool_names'] = [x.get('name') or x.get('function', {}).get('name') for x in tools]
        row['initial_payload_bytes'] = requests[0].stat().st_size
    else:
        row['initial_tool_names'] = []
    trace_records = [json.loads(p.read_text()) for p in sorted((agent / 'cli-traces').glob('*.json'))]
    if requests:
        from harbor_pi.exposure_audit import audit
        row.update(audit(row, first, messages, trace_records))
        common = [t.get('function', t) for t in first.get('tools', [])
                  if (t.get('name') or t.get('function', {}).get('name')) in {'read', 'bash', 'edit', 'write'}]
        row['native_schema_sha256'] = hashlib.sha256(json.dumps(sorted(common, key=lambda t: t['name']), sort_keys=True).encode()).hexdigest()
    # Route audit is deliberately conservative and labelled heuristic: raw
    # payloads/native tool arguments remain available for manual inspection.
    native = {'read', 'bash', 'edit', 'write', 'grep', 'find', 'ls', 'tool_search'}
    from harbor_pi.actual_tasks import FAMILIES
    selected = {'cap_brave': 'brave', 'cap_browser': 'browser', 'cap_db': 'postgres', 'cap_gh': 'github', **FAMILIES}.get(row['task'])
    selected_families=selected if isinstance(selected,tuple) else (selected,)
    external = [c for c in calls if c['name'] not in native]
    bash = '\n'.join(c.get('arguments', {}).get('command', '') for c in calls if c['name'] == 'bash')
    if selected is None:
        route = not external and not any(x in bash for x in ('bx web', 'playwright-cli', 'psql ', 'gh-github', 'curl ', 'wget '))
    elif row['mode'] == 'cli':
        patterns = {'brave': ('bx ',), 'browser': ('playwright-cli ',), 'postgres': ('psql ',), 'github': ('gh-github ', 'gh api ')}
        route = not external and all(any(p in bash for p in patterns[f]) for f in selected_families)
    else:
        # MCP's Pi tool prefix varies by server; keep the actual names.
        markers = {'brave': ('brave',), 'browser': ('browser_',), 'postgres': ('postgres', 'execute_sql'), 'github': ('github',)}
        route = all(any(any(p in c['name'] for p in markers[f]) for c in external) for f in selected_families)
        route = route and not any(x in bash for x in ('bx ', 'playwright-cli ', 'psql ', 'gh-github ', 'curl ', 'wget ', 'urllib', 'requests.'))
    initial_external = [n for n in row['initial_tool_names'] if n not in native]
    exposure = bool(requests)
    if row['mode'] == 'deferred':
        expected_search = row['catalog'] == 'full' or selected is not None
        exposure = exposure and not initial_external and (('tool_search' in row['initial_tool_names']) == expected_search)
        if selected:
            exposure = exposure and any(c['name'] == 'tool_search' for c in calls)
    elif row['mode'] == 'cli':
        exposure = exposure and not initial_external and 'tool_search' not in row['initial_tool_names']
    elif row['catalog'] == 'full' or selected:
        exposure = exposure and bool(initial_external)
    else:
        exposure = exposure and not initial_external
    exposure = exposure and row.get('skill_metadata_matches', False) and row.get('personal_context_absent', False)
    if row['mode'] == 'cli' and selected:
        route = route and row.get('skill_read_before_cli') is True
        if scope.get('trace_cli'):
            from harbor_pi.exposure_audit import programs_for
            route = route and all(any(t.get('program')==program and t.get('returncode')==0 for t in trace_records) for program in programs_for(row['task']))
    elif row['mode'] != 'cli' and trace_records:
        route = False
    if scope.get('github_repository'):
        expected_owner,expected_repo=scope['github_repository'].split('/')
        wrong=[]
        for call in external:
            if 'github' not in call['name']:continue
            args=call.get('arguments',{})
            if args.get('repo') and (args['repo']!=expected_repo or str(args.get('owner','')).lower()!=expected_owner.lower()):
                wrong.append(call['name'])
            if 'query' in args and expected_repo not in str(args['query']):
                wrong.append(call['name'])
        row['github_cross_repository_review_flags']=len(wrong)
        route=route and not wrong
    cleanup=directory/'remote-cleanup.json'
    if cleanup.is_file():
        row.update(json.loads(cleanup.read_text()))
    row.update(route_status='pass' if route else 'review', exposure_status='pass' if exposure else 'review',
               route_audit_scope='heuristic native-call/payload audit, not an OS execution firewall',
               clean_pass=bool(row['verifier_pass'] and route and exposure and not exception
                               and not row['provider_error'] and not row.get('stopping_reason')))
    row['outcome'] = trial_outcome(row)
    return row


def trial_outcome(row):
    if row.get('stopping_reason') == 'budget_exceeded':
        return 'budget_exceeded'
    if row.get('stopping_reason') == 'deadline' or row.get('process_status') == 'timeout':
        return 'deadline_exceeded'
    if row.get('provider_error') or row.get('process_status') == 'provider_blocked':
        return 'provider_error'
    if row.get('exception_type') or row.get('verifier_reward_present') is False:
        return 'infrastructure_error'
    if not row.get('verifier_pass'):
        return 'task_failure'
    return 'success' if row.get('clean_pass') else 'audit_review'


def matrix_specs(manifest):
    reps = manifest['matrix'].get('reps', 1)
    if type(reps) is not int or reps < 1:
        raise ValueError('matrix.reps must be a positive integer')
    for axis in ('models', 'modes', 'catalogs'):
        values = manifest['matrix'][axis]
        if not values or len(values) != len(set(values)):
            raise ValueError(f'Empty or duplicate matrix axis: {axis}')
    if manifest['harness'].get('harbor_skill_challenges') and (
            set(manifest['matrix']['modes']) != {'cli'}
            or any(not t.startswith('cap_') for t in manifest['tasks'])):
        raise ValueError('Skill challenges support CLI capability fixtures only')
    allowed = set(TASKS)
    if manifest['harness'].get('harbor_actual_tasks'):
        from harbor_pi.actual_tasks import TASKS as actual_tasks
        allowed |= actual_tasks
    unsupported = set(manifest['tasks']) - allowed
    if unsupported:
        raise ValueError(f'Unsupported pilot tasks: {sorted(unsupported)}')
    if reps > 1:
        # Reuse the native seeded shuffle, but Harbor still owns all execution.
        return [{k: v for k, v in spec.items() if k != 'trial_id'}
                for spec in runner.build_plan(manifest)]
    return [dict(zip(('task', 'model', 'mode', 'catalog'), values)) for values in itertools.product(
        sorted(manifest['tasks']), manifest['matrix']['models'],
        manifest['matrix']['modes'], manifest['matrix']['catalogs'])]


def run_matrix(args):
    m = runner.load_manifest(args.manifest)
    if m['harness'].get('campaign_execution_authorized', True) is not True:
        raise ValueError('Proposed campaign is not authorized; no environment or model started')
    from harbor_pi.campaign_freeze import verify_freeze
    verify_freeze(m, args.manifest)
    specs = matrix_specs(m)
    batch_size = m['harness'].get('supervised_batch_size', len(specs))
    if type(batch_size) is not int or batch_size <= 0:
        raise ValueError('supervised_batch_size must be a positive integer')
    token_cap = args.token_cap if args.token_cap is not None else m.get('budget', {}).get('aggregate_max_total_tokens', 3000000)
    max_trials = args.max_trials if args.max_trials is not None else len(specs)
    if type(token_cap) is not int or token_cap <= 0 or type(max_trials) is not int or max_trials <= 0:
        raise ValueError('Positive integer aggregate token cap and trial maximum required')
    limits = {cell_id(spec): cell_limits(m, spec) for spec in specs}
    if not docker_ready():
        raise RuntimeError('Docker/Compose unavailable')
    image = subprocess.check_output(['docker', 'image', 'inspect', m['harness']['harbor_pilot_image'], '--format', '{{.Id}}'], env=docker_env(), text=True).strip()
    if image != m['harness']['harbor_image_id']:
        raise ValueError('Image tag no longer matches frozen pilot image ID')
    # Verify the explicitly selected disposable account before any model call.
    expected_owner = os.environ.get('GITHUB_EVAL_ORG')
    if not expected_owner:
        raise ValueError('Set GITHUB_EVAL_ORG to the disposable GitHub account; no model invoked')
    check = subprocess.run([str(RIG / 'runtime/bin/gh'), 'api', 'user', '--jq', '.login'], env={**os.environ, 'GH_TOKEN': os.environ.get('STUDY_GITHUB_TOKEN', '')}, capture_output=True, text=True, timeout=30)
    if check.returncode or check.stdout.strip() != expected_owner:
        raise ValueError('GitHub token identity does not match GITHUB_EVAL_ORG; no model invoked')
    # Validate credentials and all dimensions before starting any provider call.
    for spec in specs:
        checked_spec(m, **spec)
        private_env(m, spec)
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    source_files = ['runner.py', 'harbor_pi/adapter.py', 'harbor_pi/pilot.py',
                    'harbor_pi/pilot_support.py', 'harbor_pi/route_contract.py', 'harbor_pi/pilot_verify.py',
                    'harbor_pi/search_provenance.py', 'harbor_pi/exposure_audit.py', 'harbor_pi/campaign_freeze.py']
    if m['harness'].get('harbor_skill_challenges'):
        source_files.append('harbor_pi/skill_challenge_verify.py')
    if m['harness'].get('harbor_actual_tasks'):
        from harbor_pi.browser_image import image_id
        verifier_image = image_id(m['harness']['harbor_actual_verifier_image'])
        if verifier_image != m['harness']['harbor_actual_verifier_image_id']:
            raise ValueError('Actual-task verifier image identity changed')
        source_files += ['harbor_pi/actual_tasks.py', 'harbor_pi/actual_verify.py', 'harbor_pi/pilot_image/execute.py',
                         'harbor_pi/actual_verifier/Dockerfile', 'harbor_pi/actual_verifier/requirements.txt', 'harbor_pi/browser_image.py',
                         'harbor_pi/github_tasks.py','harbor_pi/actual_verifier/v2.Dockerfile','harbor_pi/actual_verifier/requirements-v2.txt',
                         'harbor_pi/shopping_state.py','harbor_pi/shopping_original_verify.py','harbor_pi/shopping_candidate_probe.py']
    hashes = {name: hashlib.sha256((RIG / name).read_bytes()).hexdigest() for name in source_files}
    plan = {'manifest_digest': runner.sha256_json(m), 'runtime_source_hashes': hashes,
            'image_id': image, 'engineering_only': True,
            'specs': specs, 'cell_limits': limits, 'automatic_retries': 0,
            'aggregate_recorded_token_cap': token_cap, 'max_trials': max_trials,
            'supervised_batch_size': batch_size,
            'watchdog_scope': 'assistant-message usage, observation-granular; excludes auxiliary usage; not billed cost'}
    planfile = args.output / 'plan.json'
    if planfile.exists() and json.loads(planfile.read_text()) != plan:
        raise ValueError('Pilot plan changed; start a new explicitly recorded phase')
    if not planfile.exists():
        runner.atomic_write_json(planfile, plan)
    rows = []
    for spec in specs:
        directory = args.output / cell_id(spec)
        if (directory / 'scope.json').exists():
            rows.append(result_summary(directory))
    total = sum(r['total_tokens'] for r in rows)
    started_this_invocation = 0
    for spec in specs:
        if any(getattr(args, k) and spec[k] != getattr(args, k) for k in ('task', 'mode', 'model', 'catalog')):
            continue
        directory = args.output / cell_id(spec)
        if directory.exists():
            continue  # Never repeat a failed or interrupted attempt silently.
        if total >= token_cap or len(rows) >= max_trials or started_this_invocation >= batch_size:
            print('Bound reached; pending cells preserved, no replay', flush=True)
            break
        if runner.sha256_json(runner.load_manifest(args.manifest))!=plan['manifest_digest'] or any(
                hashlib.sha256((RIG/name).read_bytes()).hexdigest()!=digest for name,digest in hashes.items()):
            raise ValueError('Active phase inputs/source changed; pending cells stopped, no replay')
        verify_freeze(m, args.manifest)
        free = shutil.disk_usage(RIG).free
        if free < MIN_FREE_BYTES:
            raise ValueError(f'Free disk {free} below {MIN_FREE_BYTES} reserve; pending cells stopped, no replay')
        # Harbor owns per-trial teardown; never sweep other or interrupted projects.
        job = prepare_task(args.manifest, directory, spec)
        started_this_invocation += 1
        print('START', spec, flush=True)
        with (directory / 'harbor.log').open('w') as log:
            proc = subprocess.run([sys.executable, '-m', 'harbor_pi.bridge', 'run', str(job), '--execute'],
                                  env={**os.environ, 'PYTHONPATH': str(RIG)}, stdout=log, stderr=subprocess.STDOUT)
        row = result_summary(directory)
        if m['harness'].get('harbor_actual_tasks'):
            from harbor_pi.actual_tasks import cleanup_remote
            row.update(cleanup_remote(directory))
        row['bridge_exit_code'] = proc.returncode
        rows.append(row)
        total += row['total_tokens']
        runner.atomic_write_json(args.output / 'summary.json', {'engineering_only': True, 'planned_cells': len(specs), 'rows': rows, 'recorded_total_tokens': total, 'actual_billed_cost': None})
        print('END', {k: row.get(k) for k in ('task', 'model', 'mode', 'catalog', 'status', 'verifier_pass', 'route_status', 'exposure_status', 'total_tokens')}, flush=True)
        if (row.get('provider_error') or row.get('process_status') == 'provider_blocked'
                or row.get('remote_cleanup_status') == 'failed'
                or ((row.get('exception_type') or proc.returncode)
                    and row.get('outcome') not in {'budget_exceeded', 'deadline_exceeded'})):
            print('Infrastructure/provider error: stopping pending work for diagnosis; attempt retained', flush=True)
            break
    # Include all existing cells even on a no-op resume.
    rows = [result_summary(p) for p in sorted(args.output.iterdir()) if p.is_dir() and (p / 'scope.json').is_file()]
    runner.atomic_write_json(args.output / 'summary.json', {'engineering_only': True, 'planned_cells': len(specs), 'rows': rows, 'recorded_total_tokens': sum(r['total_tokens'] for r in rows), 'actual_billed_cost': None})
    print('Checkpoint:', args.output / 'summary.json', flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, default=MANIFEST)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--execute', action='store_true')
    p.add_argument('--max-trials', type=int, help='Frozen trial maximum; default: complete planned matrix')
    p.add_argument('--token-cap', type=int, help='Frozen aggregate recorded-token gate; default: manifest or legacy 3M')
    from harbor_pi.actual_tasks import TASKS as actual_tasks
    p.add_argument('--task', choices=sorted(TASKS | actual_tasks))
    p.add_argument('--model', choices=('gpt6luna', 'glm53flash'))
    p.add_argument('--mode', choices=runner.MODES)
    p.add_argument('--catalog', choices=('required', 'full'))
    args = p.parse_args()
    if not args.execute:
        p.error('--execute required: this spends provider tokens')
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (RIG / 'runtime/harbor-pilot-controller.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run_matrix(args)

if __name__ == '__main__':
    main()
