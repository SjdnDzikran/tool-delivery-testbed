"""Harbor-owned, zero-model baseline probe of a maintainer-published image.

No task replacement or admission: UI/operation/verifier equivalence is separate.
"""
from __future__ import annotations
import argparse
import asyncio
import fcntl
import json
import os
from pathlib import Path
import shlex
import subprocess

from harbor.environments.docker.docker import DockerEnvironment
from harbor.models.task.config import EnvironmentConfig
from harbor.models.trial.paths import TrialPaths
import runner
from harbor_pi.bridge import RIG, docker_env
from harbor_pi.real_task_inputs import UPSTREAM

IMAGE = 'am1n3e/webarena-verified-shopping_admin@sha256:d0531dd27ed98d0c459ff9e88118bf2ed8b660b0ed99c38837db46c065a5be13'


def matches(labels, values):
    return all(str(values.get(k)) == labels.get(k) for k in ('InitialGroups', 'InitialCustomers'))


async def probe(output):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    environment_dir = output / 'environment'
    environment_dir.mkdir()
    (environment_dir / 'docker-compose.yaml').write_text(json.dumps({'services': {'main': {
        'command': ['supervisord', '-n', '-j', '/supervisord.pid'],
        'environment': {'WA_ENV_CTRL_EXTERNAL_SITE_URL': 'http://localhost/'},
    }}}))
    paths = TrialPaths(output / 'trial')
    paths.mkdir()
    session = 'shopping-candidate-' + output.name
    environment = DockerEnvironment(environment_dir=environment_dir,
        environment_name='shopping-candidate', session_id=session, trial_paths=paths,
        task_env_config=EnvironmentConfig(docker_image=IMAGE, cpus=2, memory_mb=3072))
    report = {'model_calls': 0, 'image': IMAGE, 'task_replaced': False,
              'candidate_admitted': False, 'baseline_checks': 'not_completed',
              'ui_operation_and_original_verifier_checks': 'pending'}
    async def command(name, text, timeout=240):
        result = await environment.exec(text, user='root', timeout_sec=timeout)
        (output / (name + '.stdout')).write_text(result.stdout or '')
        (output / (name + '.stderr')).write_text(result.stderr or '')
        if result.return_code:
            raise RuntimeError(f'Candidate {name} failed, exit {result.return_code}; diagnostics retained')
        return result.stdout or ''
    try:
        await environment.start(force_build=False)
        await command('start', 'env-ctrl start --wait --timeout 180')
        await command('configure', 'env-ctrl init --base-url http://localhost/')
        sql = ("SELECT 'InitialGroups',COUNT(*) FROM customer_group UNION ALL "
               "SELECT 'InitialCustomers',COUNT(*) FROM customer_entity UNION ALL "
               "SELECT 'PriorTaskGroup',COUNT(*) FROM customer_group WHERE customer_group_code='Premium Europe' UNION ALL "
               "SELECT 'PriorTaskCustomer',COUNT(*) FROM customer_entity WHERE email='isabella.romano@premium.eu';")
        raw = await command('baseline', 'mysql -u magentouser -pMyPassword magentodb -NB -e ' + shlex.quote(sql))
        values = dict(line.split('\t', 1) for line in raw.splitlines() if '\t' in line)
        label_path = UPSTREAM / 'tasks/playwright_webarena/standard/shopping_admin/customer_segmentation_setup/label.txt'
        labels = dict(line.strip().split('|', 1) for line in label_path.read_text().splitlines() if '|' in line)
        report['baseline_checks'] = {
            'original_group_customer_counts_match': matches(labels, values),
            'task_mutations_absent': values.get('PriorTaskGroup') == values.get('PriorTaskCustomer') == '0',
        }
        report['admin_http_status'] = (await command('http', "curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1/admin/", 30)).strip()
    except Exception as exc:
        report['error'] = str(exc)
        raise
    finally:
        try:
            await environment.stop(delete=True)
            report['harbor_cleanup_completed'] = True
        except Exception as exc:
            report['harbor_cleanup_completed'] = False
            report['cleanup_error'] = str(exc)
        check = subprocess.run(['docker', 'image', 'inspect', IMAGE], env=docker_env(), capture_output=True)
        report['shared_image_retained'] = check.returncode == 0
        check = subprocess.run(['docker', 'ps', '-aq', '--filter', f'label=com.docker.compose.project={session}'],
                               env=docker_env(), capture_output=True, text=True)
        report['owned_containers_removed'] = check.returncode == 0 and not check.stdout.strip()
        runner.atomic_write_json(output / 'report.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if not args.execute:
        parser.error('--execute required: starts a disposable Harbor environment, no model calls')
    os.environ.update(docker_env())
    with (RIG / 'runtime/harbor-pilot-controller.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        asyncio.run(probe(args.output))
