"""Run retained positive/negative real-task wiring checks without model calls."""
import argparse
import asyncio
import fcntl
import json
import os
from pathlib import Path

from harbor.job import Job
from harbor.models.job.config import JobConfig
import runner
from harbor_pi.actual_tasks import prepare_task
from harbor_pi.bridge import RIG, docker_env
from harbor_pi.browser_image import image_id
from harbor_pi.pilot import result_summary


async def probe(manifest, output, selected=None):
    os.environ.update(docker_env())
    m = runner.load_manifest(manifest)
    for key, identity in [('harbor_pilot_image','harbor_image_id'),
                          ('harbor_actual_verifier_image','harbor_actual_verifier_image_id')]:
        if image_id(m['harness'][key]) != m['harness'][identity]:
            raise ValueError('Cached image identity mismatch')
    output.mkdir(mode=0o700)
    rows = []
    for task in m['tasks']:
        if selected and task not in selected:
            continue
        for negative in (False, True):
            spec = dict(task=task, model='glm53flash', mode='cli', catalog='required')
            root = output / (task + ('-negative' if negative else '-positive'))
            job = prepare_task(manifest, root, spec, oracle=True, negative=negative)
            execution = await Job.create(JobConfig.model_validate_json(job.read_text()))
            await execution.run()
            row = result_summary(root)
            row['expected_reward'] = 0 if negative else 1
            trial = next(root.glob('jobs/*/*/result.json'))
            outcome = json.loads(trial.read_text())
            row['reward'] = ((outcome.get('verifier_result') or {}).get('rewards') or {}).get('reward')
            row['check_pass'] = row['reward'] == row['expected_reward'] and outcome.get('exception_info') is None
            row['model_calls'] = 0
            from harbor_pi.actual_tasks import cleanup_remote
            row.update(cleanup_remote(root))
            if row.get('remote_cleanup_status')=='failed':
                row['check_pass']=False
            rows.append(row)
            (output/'summary.json').write_text(json.dumps({'fixture_only': True, 'model_calls': 0, 'rows': rows}, indent=2)+'\n')
            print(task, 'negative' if negative else 'positive', 'reward', row.get('reward'), 'check', row['check_pass'], flush=True)
            if not row['check_pass']:
                raise RuntimeError('Oracle wiring check failed; original attempt retained')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--task', action='append', help='Restrict zero-model checks; never a model retry')
    a = p.parse_args()
    with (RIG/'runtime/harbor-pilot-controller.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        asyncio.run(probe(a.manifest.resolve(), a.output.resolve(), a.task))


if __name__ == '__main__':
    main()
