"""Offline supervisor checks; subprocess/model execution is mocked."""
from contextlib import redirect_stdout
import hashlib
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

RIG = Path(__file__).resolve().parents[2]
LOADER = importlib.machinery.SourceFileLoader('main_supervisor', str(RIG/'scripts/supervise-main-v6'))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
supervisor = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(supervisor)


class MainSupervisorTests(unittest.TestCase):
    def test_paused_model_and_existing_attempt_are_skipped(self):
        m = {'harness': {}, 'tasks': {'control_1': {}}, 'matrix': {
            'models': ['a', 'b'], 'modes': ['cli'], 'catalogs': ['required'], 'reps': 3, 'seed': 2026}}
        with tempfile.TemporaryDirectory() as tmp, patch.object(supervisor, 'OUTPUT', Path(tmp)):
            state = {'blocked_models': {'a': 'quota-attempt'}}
            specs = supervisor.pending(m, state)
            self.assertEqual(len(specs), 3)
            self.assertTrue(all(s['model'] == 'b' for s in specs))
            (Path(tmp)/supervisor.cell_id(specs[0])).mkdir()
            self.assertEqual(len(supervisor.pending(m, state)), 2)

    def test_quota_pauses_only_model_but_other_errors_halt(self):
        for quota, cleanup, bounded in ((True, True, False), (False, True, False),
                                         (True, False, False), (False, True, True)):
            with self.subTest(quota=quota, cleanup=cleanup, bounded=bounded), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest = root/'manifest.toml'
                receipt = {'supervisor_sha256': hashlib.sha256(Path(supervisor.__file__).read_bytes()).hexdigest()}
                (root/'receipt.json').write_text(json.dumps(receipt))
                model = 'glm53flash'
                spec = {'task': 'control_1', 'model': model, 'mode': 'cli', 'catalog': 'required', 'rep': 1}
                row = {**spec, 'process_status': 'provider_blocked' if quota else 'incomplete',
                       'outcome': 'budget_exceeded' if bounded else 'provider_error',
                       'provider_error': not bounded, 'exception_type': 'RuntimeError'}
                with patch.object(supervisor, 'OUTPUT', root), patch.object(supervisor, 'STATE', root/'state.json'), \
                        patch.object(supervisor, 'MANIFEST', manifest), \
                        patch.object(supervisor.runner, 'load_manifest', return_value={'harness': {'execution_freeze_receipt': 'receipt.json'}}), \
                        patch.object(supervisor, 'verify_freeze'), \
                        patch.object(supervisor, 'pending', return_value=[spec]), \
                        patch.object(supervisor.subprocess, 'run', return_value=SimpleNamespace(returncode=0)), \
                        patch.object(supervisor, 'result_summary', return_value=row), \
                        patch.object(supervisor, 'cleanup_check', return_value=cleanup), \
                        patch.object(supervisor, 'status', return_value={}), redirect_stdout(io.StringIO()):
                    supervisor.run()
                    state = supervisor.load_state()
                    self.assertFalse(state['active'])
                    self.assertTrue(state['needs_review'])
                    self.assertEqual(model in state['blocked_models'], quota)
                    self.assertEqual(bool(state['halt']), not cleanup or (not quota and not bounded))
                    with self.assertRaisesRegex(RuntimeError, 'Review or diagnosis'):
                        supervisor.run()


if __name__ == '__main__':
    unittest.main()
