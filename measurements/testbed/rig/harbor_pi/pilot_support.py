"""Bounded container pilot helpers. No retry loop or personal resource loading."""
from __future__ import annotations
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import tempfile

import runner

TASKS = {'control_1', 'control_2', 'cap_brave', 'cap_browser', 'cap_db', 'cap_gh'}
PATH = '/opt/study/bin:/opt/pi/node_modules/.bin:/opt/postgres-mcp/bin:/usr/lib/postgresql/16/bin:/usr/local/bin:/usr/bin:/bin'
DSN = 'postgresql://study@127.0.0.1:5432/study'


def private_env(manifest, spec):
    """Same capability credentials in both routes; only assigned catalog keys."""
    task = manifest['tasks'][spec['task']]
    selected = set(manifest['catalog']) if spec['catalog'] == 'full' else set(task['catalog'])
    path = ('/opt/traced/bin:' if manifest['harness'].get('harbor_trace_cli') else '') + PATH
    env = {'PATH': path, 'TESTBED_PG_DSN': DSN,
           'PLAYWRIGHT_MCP_EXECUTABLE_PATH': '/opt/google/chrome/chrome',
           'PLAYWRIGHT_MCP_SANDBOX': 'true', 'PLAYWRIGHT_BROWSERS_PATH': '0',
           'GH_CONFIG_DIR': '/home/study/.config/gh-study',
           'PI_OBSERVER_DIR': '/logs/agent/requests',
           'PI_OBSERVER_RAW_DIR': '/logs/agent/raw-requests'}
    if 'brave-search' in selected:
        key = os.environ.get('BRAVE_API_KEY')
        if not key:
            raise ValueError('Brave credential unavailable; no provider call authorized')
        env.update(BRAVE_API_KEY=key, BRAVE_SEARCH_API_KEY=key)
    if 'github' in selected:
        token = os.environ.get('STUDY_GITHUB_TOKEN')
        owner = os.environ.get('GITHUB_EVAL_ORG')
        if not token or not owner:
            raise ValueError('GitHub credential and disposable GITHUB_EVAL_ORG are required')
        env.update(STUDY_GITHUB_TOKEN=token, GH_TOKEN=token, GITHUB_EVAL_ORG=owner)
        repository = os.environ.get('TESTBED_GH_REPO')
        if repository:
            env['TESTBED_GH_REPO'] = repository
    return env


async def setup(agent, environment, *, env=None):
    from harbor_pi.adapter import cell_limits
    limits = cell_limits(agent.manifest, agent.spec)
    env = dict(private_env(agent.manifest, agent.spec) if env is None else env)
    env.update(PI_TRIAL_DEADLINE_S=str(limits['watchdog_deadline_s']),
               PI_TRIAL_BUDGET_TOKENS=str(limits['max_total_tokens']))
    # Values travel in one private uploaded file, never in exec argv/logs.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'trial-env'
        path.write_text('\n'.join(f'export {k}={shlex.quote(v)}' for k, v in env.items()) + '\n')
        path.chmod(0o600)
        await environment.upload_file(path, '/home/study/.trial-env')
    result = await environment.exec('chown study:study /home/study/.trial-env && chmod 600 /home/study/.trial-env', user='root')
    if result.return_code:
        raise RuntimeError('Cannot restrict private trial environment')
    await agent._exec(environment, '''set -eu
mkdir -p .playwright artifacts /logs/agent/cli-traces
printf '%s' '{"browser":{"browserName":"chromium","isolated":true,"launchOptions":{"executablePath":"/opt/google/chrome/chrome","headless":true,"chromiumSandbox":true}}}' > .playwright/cli.config.json
/usr/lib/postgresql/16/bin/initdb -D /home/study/pgdata -A trust -U study >/logs/agent/postgres-init.log
/usr/lib/postgresql/16/bin/pg_ctl -D /home/study/pgdata -l /logs/agent/postgres.log -o '-h 127.0.0.1 -k /home/study -p 5432' -w start
/usr/lib/postgresql/16/bin/createdb -h 127.0.0.1 -U study study
/usr/local/bin/python3 /opt/study/fixture.py > /logs/agent/http.log 2>&1 < /dev/null &
''')
    # Only clean-home study authentication; no mounted host gh configuration.
    await agent._exec(environment, 'git config --global credential.https://github.com.helper \'!gh auth git-credential\'')


def merge_auth(path, provider, original, refreshed):
    """Compare-and-swap only this provider's refresh; preserve other logins.

    Never overwrite a concurrent interactive login. A separate research login
    avoids the daily Pi refresh-token lineage altogether.
    """
    if original == refreshed:
        return 'unchanged'
    if not isinstance(refreshed, dict) or refreshed.get('type') != original.get('type'):
        raise ValueError('Refreshed provider credential schema differs')
    if original.get('type') != 'oauth':
        raise ValueError('Only OAuth refreshes may change host credentials automatically')
    path = Path(path)
    with path.with_name(path.name + '.harbor.lock').open('a') as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = json.loads(path.read_text())
        if current.get(provider) != original:
            return 'concurrent-login-preserved'
        current[provider] = refreshed
        fd, name = tempfile.mkstemp(dir=path.parent, prefix='.harbor-auth-')
        try:
            with os.fdopen(fd, 'w') as out:
                json.dump(current, out)
                out.write('\n')
                out.flush()
                os.fsync(out.fileno())
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)
    return 'provider-refresh-persisted'


async def persist_auth(agent, environment):
    provider = agent.manifest['models'][agent.spec['model']]['provider']
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'auth.json'
        path.touch(mode=0o600)
        await environment.download_file('/home/study/.pi-experiment/auth.json', path)
        content = json.loads(path.read_text())
        if set(content) != {provider}:
            raise ValueError('Container auth contains unassigned providers')
        refreshed = content[provider]
        return merge_auth(agent.manifest['harness']['auth_source'], provider,
                          agent._original_provider_auth, refreshed)


def session_usage(sessions):
    """All recorded assistant, warmup, compaction and branch-summary usage.

    Native session IDs deduplicate copied branches. Ledger coverage is not
    a claim of independently reconciled provider billing or hidden operations.
    """
    seen = {}
    records, missing = [], []
    for path in sorted(Path(sessions).rglob('*.jsonl')):
        for line in path.read_text().split('\n'):
            if not line.strip():
                continue
            entry = json.loads(line)
            kind = entry.get('type')
            if kind == 'message' and entry.get('message', {}).get('role') == 'assistant':
                usage = entry['message'].get('usage')
                category = 'assistant'
            elif (kind == 'message' and entry.get('message', {}).get('role') == 'toolResult'
                  and entry['message'].get('usage')):
                usage = entry['message']['usage']
                category = 'tool_nested'
            elif kind in ('usage', 'compaction', 'branch_summary'):
                usage = entry.get('usage')
                category = entry.get('kind', kind)
            else:
                continue
            key = entry.get('id')
            digest = hashlib.sha256(json.dumps(entry, sort_keys=True).encode()).hexdigest()
            if not key:
                raise ValueError('Accountable session entry has no ID')
            if key in seen:
                if seen[key] != digest:
                    raise ValueError('Conflicting session entries with identical ID')
                continue
            seen[key] = digest
            if not usage:
                missing.append({'entry_id': key, 'category': category})
            else:
                records.append({'entry_id': key, 'category': category, 'usage': usage})
    def total(field):
        return sum(int(r['usage'].get(field, 0)) for r in records)
    return {'schema': 'native-session-ledger-v1', 'records': records,
            'missing_usage': missing, 'recorded_entries': len(seen),
            'input_tokens': total('input') + total('cacheRead') + total('cacheWrite'),
            'output_tokens': total('output'), 'cache_read_tokens': total('cacheRead'),
            'total_tokens': total('input') + total('cacheRead') + total('cacheWrite') + total('output'),
            'ledger_has_no_missing_usage': bool(records) and not missing,
            'complete_run_accounting': False, 'actual_billed_cost': None,
            'limitation': 'Recorded native ledger only; hidden/provider billing coverage not independently reconciled'}
