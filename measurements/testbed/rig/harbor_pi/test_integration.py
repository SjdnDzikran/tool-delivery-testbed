"""Offline Harbor API, manifest, adapter and trajectory tests; no Docker/models."""
import asyncio
import json
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch

from harbor.models.agent.context import AgentContext
from harbor.models.job.config import JobConfig
from harbor.models.task.task import Task
from harbor.environments.base import ExecResult

import runner
from harbor_pi.adapter import PiAgent, checked_spec, to_atif
from harbor_pi.bridge import prepare, RIG, docker_ready, result_exit_code


EVENTS = [
    {"type": "message_end", "message": {"role": "assistant", "content": [
        {"type": "toolCall", "id": "t1", "name": "bash", "arguments": {"command": "echo ok"}}],
        "usage": {"input": 10, "cacheRead": 3, "cacheWrite": 2, "output": 5}}},
    {"type": "message_end", "message": {"role": "toolResult", "toolCallId": "t1",
        "content": [{"type": "text", "text": "ok"}]}},
]


class FakeEnvironment:
    """Records boundary calls; deliberately NOT a container execution proof."""
    def __init__(self):
        self.commands = []
        self.uploads = {}

    async def exec(self, command, **kwargs):
        self.commands.append((command, kwargs))
        return ExecResult(return_code=0, stdout="1.0.4\n" if command.endswith('--version') else "")

    async def upload_file(self, source, target):
        self.uploads[target] = Path(source).read_text()

    async def download_file(self, source, target):
        Path(target).write_text(''.join(json.dumps(e) + '\n' for e in EVENTS))


class IntegrationTests(unittest.TestCase):
    def test_task_and_job_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = prepare(RIG / 'examples/smoke.toml', Path(tmp) / 'prepared', 'deferred', 'gpt6luna')
            job = JobConfig.model_validate_json(path.read_text())
            self.assertEqual(job.n_concurrent_trials, 1)
            self.assertEqual(job.n_attempts, 1)
            self.assertEqual(job.retry.max_retries, 0)
            task = Task(Path(tmp) / 'prepared/task')
            self.assertEqual(task.config.verifier.environment_mode.value, 'separate')
            env = Path(tmp) / 'prepared/task/environment'
            self.assertEqual({p.name for p in env.iterdir()}, {'Dockerfile', 'package.json', 'package-lock.json'})
            self.assertNotIn('auth.json', path.read_text())
            self.assertTrue((env.parent / 'tests/testbed/controls/control_1_filter_sort/expected/result.json').exists())
            self.assertIn('COPY . /tests', (env.parent / 'tests/Dockerfile').read_text())
            # Re-preparation cannot overwrite an existing job/attempt.
            with self.assertRaises(FileExistsError):
                prepare(RIG / 'examples/smoke.toml', path.parent, 'eager', 'gpt6luna')

    def test_verifier_exit_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = prepare(RIG / 'examples/smoke.toml', root / 'prepared', 'eager', 'gpt6luna')
            task = job.parent / 'task'
            artifacts = root / 'answer'
            artifacts.mkdir()
            import shutil
            shutil.copyfile(task / 'solution/result.json', artifacts / 'result.json')
            verifier = task / 'tests/testbed/controls/control_1_filter_sort/verify.py'
            result = subprocess.run(['python3', str(verifier), '--artifacts', str(artifacts)], capture_output=True)
            self.assertEqual(result.returncode, 0)
            script = (task / 'tests/test.sh').read_text()
            logs = root / 'logs'
            logs.mkdir()
            for code in range(5):
                command = script.replace('/logs/verifier', str(logs)).splitlines()
                command[2] = f"python3 -c 'raise SystemExit({code})'"
                result = subprocess.run(['sh', '-c', '\n'.join(command)], capture_output=True)
                self.assertEqual((logs / 'original-exit-code.txt').read_text().strip(), str(code))
                self.assertEqual(result.returncode, 4 if code == 4 else 0)
                if code != 4:
                    self.assertEqual((logs / 'reward.txt').read_text().strip(), '1' if code == 0 else '0')
                (logs / 'reward.txt').unlink(missing_ok=True)

    def test_compose_is_a_readiness_requirement(self):
        with patch('harbor_pi.bridge.subprocess.run', side_effect=[
            subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 1)]) as run:
            self.assertFalse(docker_ready())
            self.assertEqual(run.call_args.args[0], ['docker', 'compose', 'version'])

    def test_harbor_zero_cli_exit_is_not_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'result.json'
            self.assertEqual(result_exit_code(path), 1)
            for errors in (0, 1):
                path.write_text(json.dumps({'n_total_trials': 1, 'stats': {
                    'n_completed_trials': 1, 'n_errored_trials': errors}}))
                self.assertEqual(result_exit_code(path), errors)
            path.write_text('{}')
            self.assertEqual(result_exit_code(path), 1)

    def test_all_modes_and_fail_closed(self):
        m = runner.load_manifest(RIG / 'examples/smoke.toml')
        for mode in runner.MODES:
            spec = checked_spec(m, 'control_1', mode, 'gpt6luna')
            argv = runner.build_argv(m, spec, 'task', Path('/agent'), Path('/sessions'))
            self.assertIn('max', argv)
            self.assertEqual('--no-mcp' in argv, mode == 'cli')
            self.assertEqual('builtin:tool-search' in argv, mode == 'deferred')
        with self.assertRaises(ValueError):
            checked_spec(m, 'control_1', 'eager', 'gpt6luna', 'full')
        with self.assertRaises(ValueError):
            checked_spec(m, 'control_2', 'eager', 'gpt6luna')

    def test_trajectory_and_usage(self):
        trajectory, usage, errors = to_atif(EVENTS, 'task', 'openai/gpt-6-luna')
        self.assertEqual(trajectory['steps'][1]['observation']['results'][0]['source_call_id'], 't1')
        self.assertEqual(usage[0]['cacheWrite'], 2)
        self.assertFalse(errors)
        self.assertNotIn('final_metrics', trajectory)
        error = {'type': 'message_end', 'message': {'role': 'assistant', 'content': [], 'stopReason': 'error'}}
        self.assertTrue(to_atif([error], 'task', 'm')[2])
        with self.assertRaises(ValueError):
            to_atif(EVENTS[1:], 'task', 'm')

    def test_adapter_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            m = runner.load_manifest(RIG / 'examples/smoke.toml')
            auth = root / 'auth.json'
            auth.write_text(json.dumps({'openai': {'type': 'api_key', 'key': 'fake-openai'},
                                        'zai': {'type': 'api_key', 'key': 'fake-zai'}}))
            m['harness']['auth_source'] = str(auth)
            env = FakeEnvironment()
            with patch('runner.load_manifest', return_value=m):
                agent = PiAgent(manifest_path='unused', manifest_digest=runner.sha256_json(m),
                    task='control_1', mode='deferred', model='gpt6luna',
                    logs_dir=root / 'logs', model_name='openai/gpt-6-luna')
                asyncio.run(agent.setup(env))
                context = AgentContext()
                asyncio.run(agent.run('task', env, context))
                self.assertEqual(context.n_input_tokens, 15)
                self.assertIsNone(context.cost_usd)
                uploaded = json.loads(env.uploads['/home/study/.pi-experiment/auth.json'])
                self.assertEqual(set(uploaded), {'openai'})
                command, kwargs = env.commands[-1]
                self.assertIn('env -i', command)
                self.assertIn('builtin:tool-search', command)
                self.assertEqual(kwargs['user'], 'study')
                self.assertNotIn('fake-openai', command)
                self.assertFalse(json.loads((root / 'logs/usage-scope.json').read_text())['complete_run_accounting'])
                with self.assertRaises(ValueError):
                    PiAgent(manifest_path='unused', manifest_digest='changed', task='control_1',
                        mode='eager', model='gpt6luna', logs_dir=root / 'bad', model_name='openai/gpt-6-luna')


if __name__ == '__main__':
    unittest.main()
