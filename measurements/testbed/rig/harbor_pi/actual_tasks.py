"""Intended-task admission and independent verification. No probe substitution.

Task-specific setup and independent verifiers are staged outside the agent image.
Further families are admitted only when their implementations are ready.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import tempfile

from harbor.agents.capabilities import AgentCapabilities
from harbor.models.job.config import JobConfig
from harbor.models.task.task import Task
import runner
from harbor_pi.adapter import PiAgent, WORK, cell_id, cell_limits
from harbor_pi.bridge import RIG, TESTBED

FAMILIES = {'gaia_1': 'brave', 'gaia_2': 'brave',
            'employee_demographics_report': 'postgres', 'employee_hierarchy_management': 'postgres',
            'find_salient_file':'github','release_management_workflow':'github',
            'composite_1':('brave','postgres'),'composite_2':('postgres','github'),
            'products_sales_analysis':'browser','customer_segmentation_setup':'browser'}
TASKS = set(FAMILIES)
COMPOSITES={'composite_1':'composite_1_search_db','composite_2':'composite_2_db_repo'}
BROWSERS={'products_sales_analysis':'products','customer_segmentation_setup':'segmentation'}


def has_family(task,family):
    value=FAMILIES[task]
    return value==family if isinstance(value,str) else family in value


def validate(manifest, task):
    if not manifest['harness'].get('harbor_actual_tasks') or task not in TASKS:
        raise ValueError('Actual-task profile not explicitly enabled')
    assets = manifest['tasks'][task].get('assets', {})
    required = ({'schema','seed','verifier','oracle','common_verifier'} if task in COMPOSITES else
        {'brave':{'reference','verifier','oracle'}, 'postgres':{'fixture','verifier','oracle'},
         'github':{'verifier','oracle'},'browser':{'verifier','label','oracle'}}[FAMILIES[task]])
    if not required <= set(assets) or any(not Path(p).is_file() for p in assets.values()):
        raise ValueError('Missing real-task input/verifier assets')
    if task.startswith('gaia_'):
        receipt = json.loads(Path(manifest['harness']['gaia_verification_receipt']).read_text())
        reference = json.loads(Path(assets['reference']).read_text())
        checks = next((r for r in receipt.get('checks', []) if r['task_id'] == reference['task_id']), {})
        digest = hashlib.sha256(json.dumps(reference, sort_keys=True).encode()).hexdigest()
        if (not receipt.get('verified') or checks.get('candidate_sha256') != digest
                or not all(checks.get(k) for k in ('question_equal','reference_equal','level_equal'))):
            raise ValueError('Official GAIA record fidelity not established')


async def setup_inputs(agent, environment):
    task = agent.manifest['tasks'][agent.spec['task']]
    wrapper = RIG / 'harbor_pi/pilot_image/execute.py'
    await environment.upload_file(wrapper, '/opt/study/execute.py')
    result = await environment.exec('chown root:root /opt/study/execute.py && chmod 644 /opt/study/execute.py', user='root')
    if result.return_code:
        raise RuntimeError('Cannot protect actual-task watchdog overlay')
    limits = cell_limits(agent.manifest, agent.spec)
    await agent._exec(environment, 'printf %s ' + shlex.quote(
        f'\nexport PI_TRIAL_DEADLINE_S={limits["watchdog_deadline_s"]}\n'
        f'export PI_TRIAL_BUDGET_TOKENS={limits["max_total_tokens"]}\n')
        + ' >> /home/study/.trial-env')
    if agent.spec['task'] in BROWSERS:
        from harbor_pi.shopping_state import start
        await start(environment)
    if has_family(agent.spec['task'],'github'):
        await agent._exec(environment, 'printf %s ' + shlex.quote(
            '\nexport TESTBED_GH_REPO=' + shlex.quote(agent.repository) + '\n') + ' >> /home/study/.trial-env')
        await agent._exec(environment,"git config --global user.name 'Testbed Agent' && git config --global user.email testbed@example.invalid")
    if has_family(agent.spec['task'],'postgres'):
        if agent.spec['task'] in COMPOSITES:
            with tempfile.TemporaryDirectory() as tmp:
                fixture=Path(tmp)/'initial.sql'
                fixture.write_bytes(Path(task['assets']['schema']).read_bytes()+b'\n'+Path(task['assets']['seed']).read_bytes())
                await environment.upload_file(fixture,'/home/study/initial-fixture')
        else:
            await environment.upload_file(Path(task['assets']['fixture']), '/home/study/initial-fixture')
        if agent.spec['task'] == 'employee_demographics_report':
            load = '/usr/lib/postgresql/16/bin/pg_restore --exit-on-error --no-owner --no-acl -h 127.0.0.1 -U study -d study /home/study/initial-fixture'
        else:
            load = '/usr/lib/postgresql/16/bin/psql -X -w -v ON_ERROR_STOP=1 -h 127.0.0.1 -U study -d study -f /home/study/initial-fixture'
        # The dump is setup input, not an alternative file-based agent route.
        await agent._exec(environment, 'set -eu; ' + load + ' > /logs/agent/fixture-restore.log 2>&1; rm /home/study/initial-fixture')


class ActualPiAgent(PiAgent):
    def __init__(self, *, github_repository=None, github_receipt_path=None, **kwargs):
        super().__init__(**kwargs)
        self.repository=github_repository
        self.repository_receipt=Path(github_receipt_path) if github_receipt_path else None
        if has_family(self.spec['task'],'github') and not (self.repository and self.repository_receipt):
            raise ValueError('Fresh isolated GitHub target and protected receipt required')

    def provision_repository(self):
        if has_family(self.spec['task'],'github'):
            from harbor_pi.github_tasks import provision
            provision(self.spec['task'],self.repository,self.repository_receipt)

    async def setup(self, environment):
        self.provision_repository()
        await super().setup(environment)
        await setup_inputs(self, environment)

    async def run(self, instruction, environment, context):
        if has_family(self.spec['task'],'postgres'):
            instruction += '\n\nTrial connection: PostgreSQL database study; TESTBED_PG_DSN is provided in the environment.\n'
        if has_family(self.spec['task'],'github'):
            instruction += '\n\nTrial repository: ' + self.repository + '. Use only this repository for all reads and writes. '
            instruction += ('This is a fresh private publication destination seeded from cached pinned history.\n' if self.spec['task'] in COMPOSITES else 'The original repository name in the task is its upstream identity; this fresh private target preserves its pinned commit history.\n')
        if self.spec['task'] in BROWSERS:
            instruction=instruction.replace('http://localhost:7780','http://shopping')
            instruction+='\n\nTrial website: http://shopping/admin. Interact with this site through the assigned browser route.\n'
        await super().run(instruction, environment, context)


class ActualOracle(ActualPiAgent):
    capabilities = AgentCapabilities()

    @staticmethod
    def name():
        return 'actual-task-reference-oracle'

    def __init__(self, *, negative=False, **kwargs):
        super().__init__(**kwargs)
        self.negative = negative

    async def setup(self, environment):
        # No model-provider credential is read or uploaded for an oracle.
        self.provision_repository()
        await self._exec(environment, f'mkdir -p {WORK} /logs/agent')
        from harbor_pi.pilot_support import setup, private_env, PATH, DSN
        values=private_env(self.manifest,self.spec) if has_family(self.spec['task'],'github') else {'PATH':PATH,'TESTBED_PG_DSN':DSN}
        await setup(self, environment, env=values)
        await setup_inputs(self, environment)

    async def run(self, instruction, environment, context):
        task = self.manifest['tasks'][self.spec['task']]
        if self.spec['task'] in BROWSERS:
            if self.negative:
                text=Path(task['assets']['label']).read_text() if self.spec['task']=='customer_segmentation_setup' else 'incorrect'
                if '<answer>' not in text:text='<answer>\n'+text+'\n</answer>'
            else:
                await environment.upload_file(Path(task['assets']['oracle']),'/home/study/trusted-ui.py')
                await self._exec(environment,'/opt/verifier/bin/python /home/study/trusted-ui.py '+BROWSERS[self.spec['task']])
                with tempfile.TemporaryDirectory() as tmp:
                    messages=Path(tmp)/'messages.json'
                    await environment.download_file('/home/study/probe-output/oracle-messages.json',messages)
                    text=json.loads(messages.read_text())[0]['content'][0]['text']
            with tempfile.TemporaryDirectory() as tmp:
                events=Path(tmp)/'events.jsonl'
                events.write_text(json.dumps({'type':'message_end','oracle_fixture':True,'message':{
                    'role':'assistant','content':[{'type':'text','text':text}]}})+'\n')
                await environment.upload_file(events,'/logs/agent/events.jsonl')
        elif self.spec['task'] in COMPOSITES:
            await environment.upload_file(Path(task['assets']['oracle']), '/home/study/reference-oracle.py')
            await self._exec(environment,'. /home/study/.trial-env; exec /usr/local/bin/python3 /home/study/reference-oracle.py '+shlex.join([self.spec['task'],str(self.negative).lower()]))
        elif FAMILIES[self.spec['task']] == 'postgres':
            if not self.negative:
                await environment.upload_file(Path(task['assets']['oracle']), '/home/study/oracle.sql')
                await self._exec(environment, '/usr/lib/postgresql/16/bin/psql -X -w -v ON_ERROR_STOP=1 -h 127.0.0.1 -U study -d study -f /home/study/oracle.sql')
                await self._exec(environment, 'rm /home/study/oracle.sql')
        elif FAMILIES[self.spec['task']]=='github':
            await environment.upload_file(Path(task['assets']['oracle']), '/home/study/reference-oracle.py')
            await environment.upload_file(Path(task['instruction']), '/home/study/reference-instruction.md')
            command='. /home/study/.trial-env; exec /usr/local/bin/python3 /home/study/reference-oracle.py '
            command+=shlex.join([self.spec['task'],'/home/study/reference-instruction.md',str(self.negative).lower()])
            await self._exec(environment,command)
        else:
            data = json.loads(Path(task['assets']['oracle']).read_text())
            if self.negative:
                data['answer'] = 'deliberately incorrect oracle answer'
            with tempfile.TemporaryDirectory() as tmp:
                answer = Path(tmp) / 'answer.json'
                answer.write_text(json.dumps(data))
                await environment.upload_file(answer, WORK + '/answer.json')
            # Fixture-only transcript checks transfer/wiring, not live provenance.
            with tempfile.TemporaryDirectory() as tmp:
                events = Path(tmp) / 'events.jsonl'
                events.write_text(json.dumps({'fixture_sources': data['sources']}) + '\n')
                await environment.upload_file(events, '/logs/agent/events.jsonl')


def cleanup_remote(output):
    receipt=output/'github-setup.json'
    if not receipt.is_file():
        return {'remote_cleanup_status':'not-created'}
    from harbor_pi.github_tasks import archive_and_delete
    scope=json.loads((output/'scope.json').read_text())
    try:
        evidence=archive_and_delete(receipt,output/'remote-final',expected_repository=scope['github_repository'])
        status={'remote_cleanup_status':'archived-and-deleted', 'remote_bundle_sha256':evidence['bundle_sha256']}
    except Exception as exc:
        status={'remote_cleanup_status':'failed','remote_cleanup_error_type':type(exc).__name__}
    (output/'remote-cleanup.json').write_text(json.dumps(status,indent=2)+'\n')
    return status


def prepare_task(manifest_path, output, spec, oracle=False, negative=False):
    m = runner.load_manifest(manifest_path)
    validate(m, spec['task'])
    task_def = m['tasks'][spec['task']]
    sql = has_family(spec['task'],'postgres')
    github = has_family(spec['task'],'github')
    composite = spec['task'] in COMPOSITES
    browser = spec['task'] in BROWSERS
    if browser:
        from harbor_pi.shopping_state import IMAGE
        from harbor_pi.browser_image import image_id
        if not image_id(IMAGE):raise ValueError('Pinned candidate image missing; no download authorized')
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    task = output / 'task'
    env = task / 'environment'
    env.mkdir(parents=True)
    policy = env / 'seccomp.json'
    shutil.copyfile(RIG / 'harbor_pi/pilot_image/seccomp.json', policy)
    main={'security_opt':[f'seccomp={policy}'],'shm_size':'256m'}
    compose={'services':{'main':main}}
    if browser:
        from harbor_pi.shopping_state import compose as shopping_compose,marker_for
        compose=shopping_compose(main)
    (env / 'docker-compose.yaml').write_text(json.dumps(compose))
    shutil.copyfile(task_def['instruction'], task / 'instruction.md')
    tests = task / 'tests'
    tests.mkdir()
    (tests / 'Dockerfile').write_text('FROM ' + m['harness']['harbor_actual_verifier_image'] + '\nUSER root\nCOPY . /tests\nUSER study\nWORKDIR /home/study/workspace\n')
    shutil.copyfile(RIG / 'harbor_pi/actual_verify.py', tests / 'actual_verify.py')
    repository=None
    if browser:
        (tests/'site.json').write_text(json.dumps({'marker':marker_for(output),'candidate_adaptation':True}))
        (tests/'docker-compose.yaml').write_text(json.dumps(shopping_compose(main,verifier=True,marker=marker_for(output))))
        shutil.copyfile(RIG/'harbor_pi/shopping_original_verify.py',tests/'shopping_original_verify.py')
        shutil.copyfile(task_def['assets']['verifier'],tests/'upstream_verify.py')
        shutil.copyfile(task_def['assets']['label'],tests/'label.txt')
    if github:
        from harbor_pi.github_tasks import repository_for, BASES
        eval_org = os.environ.get('GITHUB_EVAL_ORG')
        if not eval_org:
            raise ValueError('Set GITHUB_EVAL_ORG to a disposable GitHub account')
        repository=repository_for(output)
        (tests/'repository.json').write_text(json.dumps({'repository':repository,'base_repository':BASES[spec['task']][0]}))
        (tests/'docker-compose.yaml').write_text(json.dumps({'services':{'main':{'environment':{
            'MCP_GITHUB_TOKEN':'${STUDY_GITHUB_TOKEN:?Dedicated study token required}',
            'GH_TOKEN':'${STUDY_GITHUB_TOKEN:?Dedicated study token required}',
            'GITHUB_TOKEN':'${STUDY_GITHUB_TOKEN:?Dedicated study token required}',
            'GITHUB_EVAL_ORG':eval_org,'TESTBED_GH_REPO':repository}}}}))
    if browser:
        pass  # Reference and label already staged only into the separate verifier.
    elif composite:
        directory=tests/'testbed/composites'/COMPOSITES[spec['task']]
        directory.mkdir(parents=True)
        shutil.copyfile(task_def['assets']['verifier'],directory/'verify.py')
        common=tests/'testbed/common';common.mkdir()
        shutil.copyfile(task_def['assets']['common_verifier'],common/'verify_lib.py')
    elif sql or github:
        shutil.copyfile(task_def['assets']['verifier'], tests / 'upstream_verify.py')
    else:
        common = tests / 'testbed/common'
        common.mkdir(parents=True)
        shutil.copyfile(TESTBED / 'common/verify_lib.py', common / 'verify_lib.py')
        gaia = tests / 'testbed/gaia'
        gaia.mkdir()
        shutil.copyfile(task_def['assets']['verifier'], gaia / 'verify_gaia.py')
        shutil.copyfile(task_def['assets']['reference'], gaia / 'task.json')
    (tests / 'test.sh').write_text('''#!/bin/sh
set -u
rm -f /logs/verifier/reward.txt /logs/verifier/reward.json
/opt/verifier/bin/python /tests/actual_verify.py ''' + (spec['task'] if composite else 'browser' if browser else 'sql' if sql else 'github' if github else 'gaia') + '''
rc=$?
printf '%s\\n' "$rc" > /logs/verifier/original-exit-code.txt
case "$rc" in
  0) printf '1\\n' > /logs/verifier/reward.txt ;;
  1|2|3) printf '0\\n' > /logs/verifier/reward.txt ;;
  *) exit "$rc" ;;
esac
''')
    agent_image=m['harness']['harbor_actual_verifier_image'] if oracle and browser else m['harness']['harbor_pilot_image']
    text = 'version = "1.0"\n[agent]\nuser="study"\ntimeout_sec=' + str(task_def['deadline_s']) + '\n[environment]\ncpus=2\nmemory_mb=3072\ndocker_image=' + json.dumps(agent_image) + '\n'
    text += '[verifier]\nuser="study"\ntimeout_sec=600\nenvironment_mode="separate"\n[verifier.environment]\ncpus=2\nmemory_mb=2048\nbuild_timeout_sec=900\n'
    paths = ['/logs/agent/events.jsonl',WORK] if browser else [WORK] if composite else [WORK + '/task-state.dump'] if sql else [WORK] if github else [WORK + '/answer.json', '/logs/agent/events.jsonl']
    if sql:
        command = '/usr/lib/postgresql/16/bin/pg_dump -Fc --no-owner --no-acl -h 127.0.0.1 -U study -d study -f ' + WORK + '/task-state.dump'
        text += '[[verifier.collect]]\nuser="study"\ntimeout_sec=240\ncommand=' + json.dumps(command) + '\n'
    if browser:
        from harbor_pi.shopping_state import DUMP,SQL,CHECKSUM
        text+='[[verifier.collect]]\nservice="shopping"\nuser="root"\ntimeout_sec=240\ncommand='+json.dumps(DUMP)+'\n'
        for path in (SQL,CHECKSUM):
            text+='[[artifacts]]\nservice="shopping"\nsource='+json.dumps(path)+'\ndestination='+json.dumps(Path(path).name)+'\n'
        if spec['mode']=='cli' and not oracle:
            command='cd '+WORK+'; HOME=/home/study /opt/pi/node_modules/.bin/playwright-cli --json list > '+WORK+'/browser-sessions.json'
            text+='[[verifier.collect]]\nuser="study"\ncommand='+json.dumps(command)+'\n'
    for path in paths:
        text += '[[artifacts]]\nsource=' + json.dumps(path) + '\ndestination=' + json.dumps(Path(path).name) + '\n'
    (task / 'task.toml').write_text(text)
    selected = m['models'][spec['model']]
    sink = output / 'agent-verifier-empty'
    sink.mkdir()
    kwargs = {'manifest_path': str(manifest_path.resolve()), 'manifest_digest': runner.sha256_json(m), **spec}
    if github:
        kwargs.update(github_repository=repository, github_receipt_path=str(output/'github-setup.json'))
    if oracle:
        kwargs['negative'] = negative
    config = {'job_name': cell_id(spec) + ('-negative' if negative else '-oracle' if oracle else ''),
        'jobs_dir': str(output / 'jobs'), 'n_attempts': 1, 'n_concurrent_trials': 1,
        'retry': {'max_retries': 0}, 'environment': {'type': 'docker', 'delete': True,
        'mounts': [{'type': 'bind', 'source': str(sink), 'target': '/logs/verifier', 'read_only': True}]},
        'agents': [{'import_path': 'harbor_pi.actual_tasks:' + ('ActualOracle' if oracle else 'ActualPiAgent'),
            'model_name': f"{selected['provider']}/{selected['id']}", 'kwargs': kwargs}],
        'tasks': [{'path': str(task)}]}
    JobConfig.model_validate(config)
    Task(task)
    (output / 'scope.json').write_text(json.dumps({'spec': spec, 'actual_workload': True,
        'engineering_only': True, 'limits': cell_limits(m, spec), 'trace_cli': True, 'oracle': oracle,
        'negative_oracle': negative, 'github_repository':repository,
        'browser_candidate_adaptation':browser,'oracle_uses_verifier_image':bool(oracle and browser),
        'image_id': m['harness']['harbor_image_id']}))
    job = output / 'job.json'
    job.write_text(json.dumps(config, indent=2) + '\n')
    return job
