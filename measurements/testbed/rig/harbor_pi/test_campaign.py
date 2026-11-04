"""Offline scheduling, budget and resume checks. No Docker, APIs or model calls."""
import asyncio
from contextlib import ExitStack, redirect_stdout
import copy
import io
import json
from pathlib import Path
import tempfile
import tomllib
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import runner
from harbor_pi.adapter import cell_id, cell_limits, checked_spec
from harbor_pi.bridge import RIG
from harbor_pi.pilot import MANIFEST, matrix_specs, run_matrix, trial_outcome

PROPOSED = RIG / 'examples/harbor-campaign-proposed-v1.toml'


class CampaignTests(unittest.TestCase):
    def test_432_unique_seeded_cells_and_limits(self):
        # Parse without resolving private fixtures so CI remains self-contained.
        m = tomllib.loads(PROPOSED.read_text())
        specs = matrix_specs(m)
        self.assertEqual(len(specs), 432)
        self.assertEqual(len({cell_id(s) for s in specs}), 432)
        self.assertEqual({s['rep'] for s in specs}, {1, 2, 3})
        self.assertEqual(matrix_specs(m), specs)
        changed = copy.deepcopy(m)
        changed['matrix']['seed'] += 1
        self.assertNotEqual(matrix_specs(changed), specs)
        self.assertEqual({cell_id(s) for s in matrix_specs(changed)}, {cell_id(s) for s in specs})
        limits = [cell_limits(m, s) for s in specs]
        self.assertEqual(sum(x['max_total_tokens'] == 6000000 for x in limits), 24)
        self.assertEqual(sum(x['max_total_tokens'] for x in limits), m['budget']['aggregate_max_total_tokens'])
        self.assertEqual({x['deadline_s'] for x in limits}, {600, 1200, 1800, 2400})
        self.assertTrue(all(x['watchdog_deadline_s'] == x['deadline_s'] - 10 for x in limits))
        self.assertIs(m['harness']['campaign_execution_authorized'], False)

    def test_spec_and_budget_validation_and_legacy_identity(self):
        m = runner.load_manifest(MANIFEST)
        legacy = checked_spec(m, 'control_1', 'cli', 'glm53flash')
        self.assertEqual(cell_id(legacy), 'control_1-glm53flash-cli-required')
        m['matrix']['reps'] = 3
        self.assertTrue(cell_id(checked_spec(m, 'control_1', 'cli', 'glm53flash', rep=2)).endswith('-r02'))
        for value in (0, -1, True, '3', 1.5):
            bad = copy.deepcopy(m);bad['matrix']['reps'] = value
            with self.assertRaises(ValueError):matrix_specs(bad)
        for value in (0, 4, True, '2'):
            with self.assertRaises(ValueError):checked_spec(m, 'control_1', 'cli', 'glm53flash', rep=value)
        m['matrix']['modes'] = ['cli', 'cli']
        with self.assertRaises(ValueError):matrix_specs(m)
        m['budget']['max_total_tokens'] = 0
        with self.assertRaises(ValueError):cell_limits(m, legacy)
        m['budget']['max_total_tokens'] = 3
        m['tasks']['control_1']['deadline_s'] = 10
        with self.assertRaises(ValueError):cell_limits(m, legacy)

    def test_prepared_repetitions_keep_kwargs_scope_and_names_distinct(self):
        from harbor.models.job.config import JobConfig
        from harbor_pi.pilot import prepare_task
        m = runner.load_manifest(MANIFEST)
        m['matrix']['reps'] = 3
        names = []
        with tempfile.TemporaryDirectory() as tmp, patch('harbor_pi.pilot.runner.load_manifest', return_value=m):
            for rep in (1, 2):
                spec = checked_spec(m, 'control_1', 'cli', 'glm53flash', rep=rep)
                path = prepare_task(MANIFEST, Path(tmp) / cell_id(spec), spec)
                job = JobConfig.model_validate_json(path.read_text())
                names.append(job.job_name)
                self.assertEqual(job.agents[0].kwargs['rep'], rep)
                scope = json.loads((path.parent / 'scope.json').read_text())
                self.assertEqual(scope['spec']['rep'], rep)
                self.assertEqual(scope['limits'], cell_limits(m, spec))
        self.assertEqual(len(set(names)), 2)

    def test_mixed_actual_campaign_routes_both_controls_to_native_preparer(self):
        from harbor_pi.pilot import prepare_task
        m = runner.load_manifest(MANIFEST)
        m['harness']['harbor_actual_tasks'] = True
        with tempfile.TemporaryDirectory() as tmp, \
                patch('harbor_pi.pilot.runner.load_manifest', return_value=m), \
                patch('harbor_pi.actual_tasks.prepare_task', side_effect=AssertionError('Control misrouted')) as actual:
            for task in ('control_1', 'control_2'):
                for mode in ('eager', 'deferred', 'cli'):
                    spec = checked_spec(m, task, mode, 'glm53flash')
                    path = prepare_task(MANIFEST, Path(tmp)/cell_id(spec), spec)
                    job = json.loads(path.read_text())
                    self.assertEqual(job['agents'][0]['import_path'], 'harbor_pi.adapter:PiAgent')
                    self.assertTrue((path.parent/'scope.json').is_file())
                    self.assertTrue((path.parent/'task/tests/test.sh').is_file())
            actual.assert_not_called()

    def test_execution_freeze_rejects_changed_manifest_and_source(self):
        from harbor_pi.campaign_freeze import verify_freeze
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'manifest.toml'
            path.write_text('frozen')
            m = {'harness': {'execution_freeze_receipt': 'receipt.json'}}
            import hashlib
            receipt = {'kind': 'execution_freeze_not_launch_clearance',
                'manifest_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'resolved_manifest_digest': runner.sha256_json(m),
                'execution_source_hashes': {'test.py': 'hash'}, 'harbor_version': '0.23.0'}
            (path.parent / 'receipt.json').write_text(json.dumps(receipt))
            with patch('harbor_pi.campaign_freeze.execution_hashes', return_value={'test.py': 'hash'}), \
                    patch('harbor_pi.campaign_freeze.importlib.metadata.version', return_value='0.23.0'):
                verify_freeze(m, path)
                path.write_text('changed')
                with self.assertRaisesRegex(ValueError, 'freeze drift'):verify_freeze(m, path)
                path.write_text('frozen')
                with patch('harbor_pi.campaign_freeze.execution_hashes', return_value={'test.py': 'changed'}):
                    with self.assertRaisesRegex(ValueError, 'freeze drift'):verify_freeze(m, path)

    def test_common_setup_uploads_resolved_watchdog_limits(self):
        from harbor_pi.pilot_support import setup
        uploaded = []
        async def upload(path, target):
            uploaded.append(Path(path).read_text())
        agent = SimpleNamespace(manifest={'tasks': {'control_1': {'deadline_s': 600}},
            'budget': {'max_total_tokens': 3000000}}, spec={'task': 'control_1', 'mode': 'cli'}, _exec=AsyncMock())
        env = SimpleNamespace(upload_file=AsyncMock(side_effect=upload),
            exec=AsyncMock(return_value=SimpleNamespace(return_code=0)))
        asyncio.run(setup(agent, env, env={'PATH': '/fixture'}))
        self.assertIn('export PI_TRIAL_BUDGET_TOKENS=3000000', uploaded[0])
        self.assertIn('export PI_TRIAL_DEADLINE_S=590', uploaded[0])

    def test_actual_browser_overlay_uses_eager_exception_only(self):
        from harbor_pi.actual_tasks import setup_inputs
        for mode, cap in (('eager', 6000000), ('deferred', 3000000), ('cli', 3000000)):
            agent = SimpleNamespace(manifest={'tasks': {'products_sales_analysis': {
                'deadline_s': 2400, 'catalog': ['playwright']}},
                'budget': {'max_total_tokens': 3000000, 'browser_eager_max_tokens': 6000000}},
                spec={'task': 'products_sales_analysis', 'mode': mode}, _exec=AsyncMock())
            env = SimpleNamespace(upload_file=AsyncMock(), exec=AsyncMock(return_value=SimpleNamespace(return_code=0)))
            with patch('harbor_pi.shopping_state.start', new_callable=AsyncMock):
                asyncio.run(setup_inputs(agent, env))
            commands = '\n'.join(str(c) for c in agent._exec.call_args_list)
            self.assertIn(f'PI_TRIAL_BUDGET_TOKENS={cap}', commands)
            self.assertIn('PI_TRIAL_DEADLINE_S=2390', commands)

    def test_outcomes_keep_caps_separate_from_task_failure(self):
        self.assertEqual(trial_outcome({'stopping_reason': 'budget_exceeded', 'exception_type': 'RuntimeError'}), 'budget_exceeded')
        self.assertEqual(trial_outcome({'process_status': 'timeout'}), 'deadline_exceeded')
        self.assertEqual(trial_outcome({'provider_error': True}), 'provider_error')
        self.assertEqual(trial_outcome({'exception_type': 'RuntimeError'}), 'infrastructure_error')
        self.assertEqual(trial_outcome({'verifier_reward_present': False}), 'infrastructure_error')
        self.assertEqual(trial_outcome({'verifier_pass': False}), 'task_failure')
        self.assertEqual(trial_outcome({'verifier_pass': True, 'clean_pass': True}), 'success')

    def test_proposed_campaign_refuses_before_docker_or_models(self):
        m = tomllib.loads(PROPOSED.read_text())
        with patch('harbor_pi.pilot.runner.load_manifest', return_value=m), patch('harbor_pi.pilot.docker_ready') as docker:
            with self.assertRaisesRegex(ValueError, 'not authorized'):
                run_matrix(SimpleNamespace(manifest=PROPOSED))
            docker.assert_not_called()

    def test_mocked_controller_resume_freeze_and_aggregate_gate(self):
        for aggregate, fail_first, bounded_first, from_manifest, bridge_first, batch in (
                (100, True, False, False, False, 3), (5, False, False, False, False, 3),
                (100, False, True, False, False, 3), (5, False, False, True, False, 3),
                (100, False, False, False, True, 3), (100, False, False, False, False, 1)):
            with self.subTest(aggregate=aggregate, bounded=bounded_first, from_manifest=from_manifest, bridge=bridge_first), tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
                m = runner.load_manifest(MANIFEST)
                m['harness']['campaign_execution_authorized'] = True  # Explicitly enable only this mocked controller test.
                m['tasks'] = {'control_1': m['tasks']['control_1']}
                m['matrix'].update(models=['glm53flash'], modes=['cli'], catalogs=['required'], reps=3)
                m['budget']['aggregate_max_total_tokens'] = aggregate
                m['harness']['supervised_batch_size'] = batch
                args = SimpleNamespace(manifest=MANIFEST, output=Path(tmp), token_cap=None if from_manifest else aggregate,
                    max_trials=None, task=None, model=None, mode=None, catalog=None)
                created = []
                summaries = {}
                def prepare(manifest, directory, spec):
                    directory.mkdir()
                    (directory / 'scope.json').write_text(json.dumps({'spec': spec}))
                    created.append(cell_id(spec))
                    summaries[directory] = {**spec, 'total_tokens': 3, 'verifier_pass': not (fail_first and len(created) == 1),
                        'provider_error': fail_first and len(created) == 1, 'status': 'completed',
                        'exception_type': 'RuntimeError' if bounded_first and len(created) == 1 else None,
                        'outcome': 'budget_exceeded' if bounded_first and len(created) == 1 else 'success'}
                    return directory / 'job.json'
                stack.enter_context(patch.dict('os.environ', {'GITHUB_EVAL_ORG':'test-owner'}))
                stack.enter_context(patch('harbor_pi.pilot.runner.load_manifest', return_value=m))
                stack.enter_context(patch('harbor_pi.pilot.docker_ready', return_value=True))
                stack.enter_context(patch('harbor_pi.pilot.subprocess.check_output', return_value=m['harness']['harbor_image_id']))
                def execute(argv, **kwargs):
                    failed = (bridge_first or bounded_first) and '-m' in argv and len(created) == 1
                    return SimpleNamespace(returncode=int(failed), stdout='test-owner')
                command = stack.enter_context(patch('harbor_pi.pilot.subprocess.run', side_effect=execute))
                stack.enter_context(patch('harbor_pi.pilot.private_env', return_value={}))
                stack.enter_context(patch('harbor_pi.pilot.prepare_task', side_effect=prepare))
                stack.enter_context(patch('harbor_pi.pilot.result_summary', side_effect=lambda p: summaries[p]))
                stack.enter_context(redirect_stdout(io.StringIO()))
                run_matrix(args)
                self.assertEqual(len(created), 1 if fail_first or bridge_first or batch == 1 else 3 if bounded_first else 2)
                run_matrix(args)
                self.assertEqual(len(created), 2 if aggregate == 5 or batch == 1 else 3)
                run_matrix(args)
                self.assertEqual(len(created), len(set(created)))
                self.assertEqual(len(created), 2 if aggregate == 5 else 3)
                bridge_calls = [c for c in command.call_args_list if '-m' in c.args[0]]
                self.assertEqual(len(bridge_calls), len(created))
                plan = json.loads((args.output / 'plan.json').read_text())
                self.assertEqual(plan['aggregate_recorded_token_cap'], aggregate)
                self.assertEqual(plan['max_trials'], 3)
                self.assertEqual(plan['supervised_batch_size'], batch)
                self.assertEqual(len(plan['cell_limits']), 3)
                args.token_cap = aggregate + 1
                with self.assertRaisesRegex(ValueError, 'plan changed'):run_matrix(args)


if __name__ == '__main__':
    unittest.main()
