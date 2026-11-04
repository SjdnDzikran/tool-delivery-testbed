"""Stage the twelve intended task inputs separately from verifier references.

This is a source bundle, NOT a runnable Harbor manifest or task-admission claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from urllib.request import urlopen

import runner
from harbor_pi.bridge import RIG, TESTBED

COMMIT = 'cd45b7f57923b9b3985467f5139927575f83141c'
ROOT = RIG / 'runtime/real-task-preparation'
UPSTREAM = ROOT / 'mcpmark'
MCP_TASKS = {
    'employee_demographics_report': 'postgres/standard/employees/employee_demographics_report',
    'employee_hierarchy_management': 'postgres/standard/chinook/employee_hierarchy_management',
    'find_salient_file': 'github/standard/missing-semester/find_salient_file',
    'release_management_workflow': 'github/standard/harmony/release_management_workflow',
    'products_sales_analysis': 'playwright_webarena/standard/shopping_admin/products_sales_analysis',
    'customer_segmentation_setup': 'playwright_webarena/standard/shopping_admin/customer_segmentation_setup',
}
def gaia_task_ids():
    """Read only locally supplied, git-ignored GAIA task files."""
    return tuple(p.stem for p in sorted((TESTBED / 'gaia/gaia_tasks').glob('*.json')))



def put(path, data):
    """Reuse byte-identical inputs; never silently change an existing source bundle."""
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f'Staged input changed: {path}; use a new bundle directory')
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def postgres_fixtures():
    """Cache the pinned sample dumps used in the earlier feasibility checks.

    The MCPMark storage endpoint returned 403; this is an explicit alternative
    source, not a claim that the uninspected upstream backup bytes are identical.
    """
    commit = 'b54cb67534bf20775803b181b7a1c6f573422161'
    repo = 'neondatabase-labs/postgres-sample-dbs'
    root = ROOT / 'postgres-fixtures'
    receipt = root / 'receipt.json'
    root.mkdir(parents=True, exist_ok=True)
    if receipt.exists():
        record = json.loads(receipt.read_text())
        if (record.get('commit') != commit or record.get('repository') != repo
                or set(record.get('files', {})) != {'employees.sql.gz', 'chinook.sql', 'LICENSE'}):
            raise ValueError('Fixture cache source changed')
        for name, entry in record['files'].items():
            if hashlib.sha256((root / name).read_bytes()).hexdigest() != entry['sha256']:
                raise ValueError('Cached PostgreSQL fixture changed')
        print('Reusing verified sample-dump cache; no download')
        return record
    with urlopen(f'https://api.github.com/repos/{repo}/git/trees/{commit}', timeout=60) as response:
        tree = {entry['path']: entry for entry in json.load(response)['tree']}
    files = {}
    for name in ('employees.sql.gz', 'chinook.sql', 'LICENSE'):
        url = f'https://raw.githubusercontent.com/{repo}/{commit}/{name}'
        path = root / name
        if path.exists():
            data = path.read_bytes()
        else:
            with urlopen(url, timeout=120) as response:
                data = response.read(tree[name]['size'] + 1)
        blob = b'blob ' + str(len(data)).encode() + b'\0' + data
        if len(data) != tree[name]['size'] or hashlib.sha1(blob).hexdigest() != tree[name]['sha']:
            raise ValueError(f'Sample dump does not match pinned Git blob: {name}')
        files[name] = {'sha256': put(path, data), 'bytes': len(data),
                       'git_blob': tree[name]['sha'], 'source': url}
    record = {'repository': repo, 'commit': commit, 'files': files,
              'upstream_backup_equivalence_pending': True, 'model_calls': 0}
    put(receipt, (json.dumps(record, indent=2) + '\n').encode())
    return record


def gaia_instruction(task):
    # Neither reference answer nor provenance metadata enters the agent input.
    return (task['question'].strip() + '\n\nWrite answer.json containing an "answer" string '
            'and a "sources" array of objects with "url" and "quote" strings. '
            'Use supporting HTTP(S) sources and verbatim supporting quotations.\n').encode()


def prepare(output=ROOT / 'task-inputs-v1'):
    task_ids = gaia_task_ids()
    if len(task_ids) != 2:
        raise ValueError('Place exactly two authorized task JSON files in gaia/gaia_tasks/ before staging')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    head = subprocess.check_output(['git', '-C', str(UPSTREAM), 'rev-parse', 'HEAD'], text=True).strip()
    if head != COMMIT:
        raise ValueError('MCPMark checkout differs from the selected source revision')
    def upstream(path):
        return subprocess.check_output(['git', '-C', str(UPSTREAM), 'show', f'{COMMIT}:{path}'])
    put(output / 'MCPMark-LICENSE', upstream('LICENSE'))
    tasks = {}
    for name, relative in MCP_TASKS.items():
        prefix = 'tasks/' + relative
        instruction = upstream(prefix + '/description.md')
        adaptation = None
        if name == 'release_management_workflow':
            source = TESTBED / 'mcpmark-adaptations.md'
            amendment = '\n'.join(line[2:] for line in source.read_text().splitlines() if line.startswith('> '))
            if not amendment.startswith('**Step 7') or 'squash and merge' not in amendment:
                raise ValueError('Approved release instruction amendment is missing')
            instruction += ('\n\n' + amendment + '\n').encode()
            adaptation = put(output / name / 'verifier/adaptation-record.md', source.read_bytes())
        tasks[name] = {
            'source': f'eval-sys/mcpmark@{COMMIT}:{prefix}',
            'instruction_sha256': put(output / name / 'input/instruction.md', instruction),
            'verifier_sha256': put(output / name / 'verifier/verify.py', upstream(prefix + '/verify.py')),
            'adaptation_record_sha256': adaptation,
            'harbor_integration_pending': True,
        }
    for task_id in task_ids:
        source = TESTBED / 'gaia/gaia_tasks' / (task_id + '.json')
        task = json.loads(source.read_text())
        name = 'gaia_' + task_id
        tasks[name] = {
            'source': str(source.relative_to(TESTBED)),
            'instruction_sha256': put(output / name / 'input/instruction.md', gaia_instruction(task)),
            'reference_sha256': put(output / name / 'verifier/task.json', source.read_bytes()),
            'verifier_sha256': put(output / name / 'verifier/verify_gaia.py', (TESTBED / 'gaia/verify_gaia.py').read_bytes()),
            'official_source_and_admission_pending': True,
            'harbor_integration_pending': True,
        }
    for category, names in {
        'controls': ('control_1_filter_sort', 'control_2_group_aggregate'),
        'composites': ('composite_1_search_db', 'composite_2_db_repo'),
    }.items():
        for name in names:
            source = TESTBED / category / name
            tasks[name] = {
                'source': str(source.relative_to(TESTBED)),
                'instruction_sha256': put(output / name / 'input/instruction.md', (source / 'instruction.md').read_bytes()),
                'verifier_sha256': put(output / name / 'verifier/verify.py', (source / 'verify.py').read_bytes()),
                'harbor_integration_pending': category != 'controls',
            }
    assert len(tasks) == 12
    bundle = {'source_bundle_only': True, 'runnable_manifest': False,
              'mcpmark_commit': COMMIT, 'tasks': tasks}
    put(output / 'bundle.json', (json.dumps(bundle, indent=2) + '\n').encode())
    print('Staged twelve task inputs; references kept outside input directories:', output)
    return bundle


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, default=ROOT / 'task-inputs-v1')
    p.add_argument('--postgres-fixtures', action='store_true')
    args = p.parse_args()
    prepare(args.output)
    if args.postgres_fixtures:
        postgres_fixtures()
