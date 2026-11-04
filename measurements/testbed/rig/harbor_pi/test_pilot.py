"""Offline pilot regression checks; no provider/network/container calls."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harbor.models.job.config import JobConfig
from harbor.models.task.task import Task
import runner
from harbor_pi.adapter import checked_spec
from harbor_pi.bridge import RIG
from harbor_pi.pilot import MANIFEST, prepare_task
from harbor_pi.pilot_support import TASKS, merge_auth, private_env, session_usage
from harbor_pi.route_contract import CONTRACT, instruction_for
from harbor_pi.search_provenance import result_pairs
from harbor_pi.exposure_audit import audit


class PilotTests(unittest.TestCase):
    def test_manifest_task_subset_defines_bounded_matrix(self):
        from harbor_pi.pilot import matrix_specs
        m = runner.load_manifest(MANIFEST)
        self.assertEqual(len(matrix_specs(m)), 72)
        m['tasks'] = {k: v for k, v in m['tasks'].items() if k.startswith('cap_')}
        m['matrix'].update(models=['gpt6luna'], modes=['cli'])
        specs = matrix_specs(m)
        self.assertEqual(len(specs), 8)
        self.assertEqual({s['task'] for s in specs}, set(m['tasks']))
        self.assertTrue(all(s['model'] == 'gpt6luna' and s['mode'] == 'cli' for s in specs))
        m['tasks']['misspelled_task'] = {}
        with self.assertRaisesRegex(ValueError, 'Unsupported pilot tasks'):
            matrix_specs(m)

    def test_matrix_and_container_boundaries(self):
        m = runner.load_manifest(MANIFEST)
        for task in sorted(TASKS):
            for mode in runner.MODES:
                for model in m['models']:
                    for catalog in ('required', 'full'):
                        spec = checked_spec(m, task, mode, model, catalog)
                        self.assertEqual(spec['catalog'], catalog)
        with tempfile.TemporaryDirectory() as tmp:
            for task in sorted(TASKS):
                path = prepare_task(MANIFEST, Path(tmp) / task,
                                    checked_spec(m, task, 'cli', 'glm53flash', 'full'))
                job = JobConfig.model_validate_json(path.read_text())
                self.assertIs(json.loads(path.read_text())['environment']['delete'], True)
                self.assertTrue(job.environment.delete)
                self.assertTrue(job.environment.mounts[-1]['read_only'])
                self.assertEqual(job.environment.mounts[-1]['target'], '/logs/verifier')
                self.assertIn('rm -f /logs/verifier/reward.txt', (path.parent / 'task/tests/test.sh').read_text())
                t = Task(path.parent / 'task')
                self.assertEqual(t.config.verifier.environment_mode.value, 'separate')
                self.assertIsNotNone(t.config.verifier.environment)
                self.assertIsNone(t.config.verifier.environment.docker_image)
                env = path.parent / 'task/environment'
                self.assertEqual({p.name for p in env.iterdir()}, {'seccomp.json', 'docker-compose.yaml'})
                self.assertNotIn('privileged', (env / 'docker-compose.yaml').read_text())
                self.assertEqual(len(t.config.verifier.collect), int(task == 'cap_db'))

    def test_assigned_secrets_only(self):
        m = runner.load_manifest(MANIFEST)
        with patch.dict('os.environ', {'BRAVE_API_KEY': 'fake-brave', 'STUDY_GITHUB_TOKEN': 'fake-study'}):
            for mode in runner.MODES:
                empty = private_env(m, checked_spec(m, 'control_1', mode, 'glm53flash'))
                self.assertNotIn('BRAVE_API_KEY', empty)
                self.assertNotIn('GH_TOKEN', empty)
                full = private_env(m, checked_spec(m, 'control_1', mode, 'glm53flash', 'full'))
                self.assertEqual(full['GH_TOKEN'], 'fake-study')
                self.assertEqual(full['BRAVE_SEARCH_API_KEY'], 'fake-brave')

    def test_auth_refresh_compare_swap(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'auth.json'
            old = {'type': 'oauth', 'refresh': 'fake-old'}
            new = {'type': 'oauth', 'refresh': 'fake-new'}
            path.write_text(json.dumps({'openai': old, 'zai': {'key': 'fake-other'}}))
            self.assertEqual(merge_auth(path, 'openai', old, new), 'provider-refresh-persisted')
            self.assertEqual(json.loads(path.read_text())['zai'], {'key': 'fake-other'})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(merge_auth(path, 'openai', old, {'type': 'oauth', 'refresh': 'third'}), 'concurrent-login-preserved')
            self.assertEqual(json.loads(path.read_text())['openai'], new)

    def test_common_contract_and_search_parsing(self):
        m = runner.load_manifest(MANIFEST)
        self.assertEqual(instruction_for(m, 'task'), CONTRACT + '\n\ntask')
        self.assertEqual(instruction_for({'harness': {}}, 'task'), 'task')
        with self.assertRaises(ValueError):
            instruction_for({'harness': {'harbor_route_contract': 'unrecognized'}}, 'task')
        text = 'log header\n' + json.dumps({'infobox': {'results': [{'url': 'https://wrong.test', 'title': 'Not a web result'}]}, 'web': {'results': [{'url': 'https://a.test', 'title': 'A'}, {'url': 'https://b.test', 'title': 'B'}]}})
        self.assertEqual(result_pairs(text)[0], {'url': 'https://a.test', 'title': 'A'})
        self.assertEqual(len(result_pairs('{"url":"a","title":"A"}\n{"url":"b","title":"B"}')), 2)

    def test_skill_before_command_substitution(self):
        row = {'mode': 'cli', 'catalog': 'required', 'task': 'cap_db'}
        first = {'messages': [{'role': 'system', 'content': '<skill>\n<name>psql</name></skill>'}]}
        read = {'role': 'assistant', 'content': [{'type': 'toolCall', 'id': 'read1', 'name': 'read', 'arguments': {'path': '/home/study/.pi-experiment/skills/psql/SKILL.md'}}]}
        result = {'role': 'toolResult', 'toolCallId': 'read1', 'isError': False}
        command = {'role': 'assistant', 'content': [{'type': 'toolCall', 'id': 'b1', 'name': 'bash', 'arguments': {'command': 'count=$(psql "$TESTBED_PG_DSN" -Atqc "SELECT 1")'}}]}
        self.assertTrue(audit(row, first, [read, result, command], [])['skill_read_before_cli'])
        self.assertFalse(audit(row, first, [command, read, result], [])['skill_read_before_cli'])
        self.assertTrue(audit(row, first, [read, result, command], [])['skill_metadata_matches'])

    def test_api_key_mutation_never_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'auth.json'
            original = {'type': 'api_key', 'key': 'fake-original'}
            path.write_text(json.dumps({'zai': original}))
            with self.assertRaisesRegex(ValueError, 'Only OAuth'):
                merge_auth(path, 'zai', original, {'type': 'api_key', 'key': 'fake-changed'})
            self.assertEqual(json.loads(path.read_text())['zai'], original)
            self.assertEqual(merge_auth(path, 'zai', original, original), 'unchanged')

    def test_unicode_and_nested_tool_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entry = {'id': 'nested', 'type': 'message', 'message': {'role': 'toolResult', 'content': 'a\u2028b\u2029c', 'usage': {'input': 2, 'cacheRead': 3, 'cacheWrite': 4, 'output': 5, 'reasoning': 5}}}
            (root / 'session.jsonl').write_text(json.dumps(entry, ensure_ascii=False) + '\n')
            ledger = session_usage(root)
            self.assertEqual(ledger['total_tokens'], 14)
            self.assertEqual(ledger['records'][0]['category'], 'tool_nested')

    def test_export_allowlist(self):
        from harbor_pi.export_evidence import export
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'plan.json').write_text(json.dumps({'specs': [{}], 'image_id': 'test-image', 'manifest_digest': 'test-digest'}))
            cell = root / 'cell'
            cell.mkdir()
            (cell / 'scope.json').write_text('{}')
            agent = cell / 'jobs/job/task__fake/agent'
            agent.mkdir(parents=True)
            (agent / 'session-usage.json').write_text(json.dumps({'input_tokens': 5, 'output_tokens': 6, 'cache_read_tokens': 1, 'total_tokens': 11, 'records': [{'category': 'assistant', 'usage': {'input': 2, 'output': 4, 'cacheRead': 1}}, {'category': 'compaction', 'usage': {'input': 2, 'output': 2}}]}))
            with patch('harbor_pi.export_evidence.result_summary', return_value={'task': 'control_1', 'total_tokens': 11, 'api_key': 'fake-sensitive-value', 'raw_prompt': 'fake-private-prompt'}) as summarize:
                proof = export(Path(os.path.relpath(root)))
                self.assertTrue(summarize.call_args.args[0].is_absolute())
            self.assertEqual(proof['attempted_cells'], 1)
            self.assertEqual(proof['recorded_tokens'], 11)
            self.assertEqual(proof['rows'][0]['usage_totals']['auxiliary_tokens'], 4)
            self.assertEqual(proof['rows'][0]['usage_totals']['cache_write_tokens'], 0)
            self.assertNotIn('fake-sensitive-value', json.dumps(proof))
            self.assertNotIn('fake-private-prompt', json.dumps(proof))

    def test_explicit_closed_stdin(self):
        import subprocess, sys
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code = 'import sys,json;assert sys.stdin.read()=="";print(json.dumps({"type":"agent_settled"}))'
            run = runner.PiRun([sys.executable, '-c', code], root, {}, root / 'events', root / 'stderr', 5, 100)
            with patch('runner.subprocess.Popen', wraps=subprocess.Popen) as spawn:
                run.execute()
                self.assertEqual(spawn.call_args.kwargs['stdin'], subprocess.DEVNULL)
            self.assertTrue(run.settled)

    def test_session_auxiliary_usage_deduplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            usage = {'input': 10, 'cacheRead': 5, 'cacheWrite': 2, 'output': 3}
            entries = [
                {'id': 'm1', 'type': 'message', 'message': {'role': 'assistant', 'usage': usage}},
                {'id': 'u1', 'type': 'usage', 'kind': 'cache_warm', 'usage': usage},
                {'id': 'c1', 'type': 'compaction', 'usage': usage},
                {'id': 'b1', 'type': 'branch_summary', 'usage': usage},
            ]
            (root / 'one.jsonl').write_text('\n'.join(json.dumps(e) for e in entries))
            (root / 'branch.jsonl').write_text(json.dumps(entries[0]))
            actual = session_usage(root)
            self.assertEqual(actual['total_tokens'], 80)
            self.assertEqual(actual['input_tokens'], 68)
            self.assertEqual(actual['cache_read_tokens'], 20)
            self.assertTrue(actual['ledger_has_no_missing_usage'])
            self.assertFalse(actual['complete_run_accounting'])
            (root / 'missing.jsonl').write_text(json.dumps({'id': 'missing', 'type': 'compaction'}))
            self.assertFalse(session_usage(root)['ledger_has_no_missing_usage'])
            (root / 'conflict.jsonl').write_text(json.dumps({'id': 'u1', 'type': 'usage', 'kind': 'cache_warm', 'usage': {'input': 99}}))
            with self.assertRaises(ValueError):
                session_usage(root)

    def test_repetitions_expand_engineering_matrix_without_collisions(self):
        from harbor_pi.pilot import matrix_specs, cell_id
        manifest = runner.load_manifest(MANIFEST)
        manifest['matrix']['reps'] = 3
        specs = matrix_specs(manifest)
        self.assertEqual(len(specs), 216)
        self.assertEqual(len({cell_id(s) for s in specs}), 216)

    def test_unverified_leftover_sweeping_is_disabled(self):
        from harbor_pi.pilot import sweep_trial_leftovers
        with patch('harbor_pi.pilot.subprocess.run') as command:
            with self.assertRaisesRegex(RuntimeError, 'sweeping disabled'):
                sweep_trial_leftovers(Path('/unused'))
            command.assert_not_called()

if __name__ == '__main__':
    unittest.main()
