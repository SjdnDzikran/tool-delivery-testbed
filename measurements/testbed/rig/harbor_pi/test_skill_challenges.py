"""Synthetic offline verifier controls; no model, network or container calls."""
import asyncio
import json
import re
from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from harbor.models.task.task import Task
import runner
from harbor_pi.bridge import RIG
from harbor_pi.pilot import matrix_specs, prepare_task
from harbor_pi import skill_challenge_verify as v
from harbor_pi.skill_challenge_oracle import SkillChallengeOracle

MANIFEST = RIG / 'examples/harbor-skill-challenges.toml'


class SkillChallengeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.traces = self.root / 'traces'
        self.traces.mkdir()
        self.patcher = patch.multiple(v, TRACE_ROOT=self.traces,
            DB_STATE=self.root / 'db-state.json', DB_ROUNDTRIP=self.root / 'db-csv-roundtrip.json',
            BROWSER_SESSIONS=self.root / 'browser-sessions.json')
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def capture(self, program, value):
        path = self.traces / f'{len(list(self.traces.glob("*.json")))}.json'
        path.write_text(json.dumps({'program': program, 'returncode': 0}))
        path.with_suffix('.stdout').write_text(value if isinstance(value, str) else json.dumps(value))

    def test_prepare_is_cli_only_and_separate(self):
        m = runner.load_manifest(MANIFEST)
        specs = matrix_specs(m)
        self.assertEqual(len(specs), 8)
        for s in specs:
            job = prepare_task(MANIFEST, self.root / '-'.join(s.values()), s)
            task = Task(job.parent / 'task')
            self.assertEqual(task.config.verifier.environment_mode.value, 'separate')
            self.assertEqual((job.parent / 'task/tests/verify.py').read_text(), Path(v.__file__).read_text())
            self.assertIn('/logs/agent/cli-traces', (job.parent / 'task/task.toml').read_text())
        m['matrix']['modes'].append('eager')
        with self.assertRaisesRegex(ValueError, 'CLI capability'):
            matrix_specs(m)
        self.assertIsNot(SkillChallengeOracle.run, SkillChallengeOracle.__mro__[1].run)
        fake = SimpleNamespace(spec={'task': 'cap_brave'}, logs_dir=self.root, recovery_csv=None,
            _exec=AsyncMock(return_value=SimpleNamespace(stdout=None)))
        asyncio.run(SkillChallengeOracle.run(fake, '', None, None))
        self.assertEqual(json.loads((self.root / 'oracle-proof.json').read_text())['model_calls'], 0)

    def test_brave_capture_constraints(self):
        top = {'url': 'https://example.test/', 'title': 'Synthetic fixture'}
        (self.root / 'brave.json').write_text(json.dumps(top))
        self.capture('bx', {'query': {'original': 'Universitas Gadjah Mada official website',
            'country': 'id', 'spellcheck_off': True}, 'web': {'results': [top]}})
        self.assertEqual(v.verify('cap_brave', self.root), 0)
        (self.root / 'brave.json').write_text(json.dumps({**top, 'title': 'Wrong'}))
        self.assertEqual(v.verify('cap_brave', self.root), 1)

    def test_browser_requires_close_and_empty_registry(self):
        (self.root / 'token.txt').write_text(v.TOKEN+'\n')
        (self.root / 'browser-state.json').write_text(json.dumps({'origins': [{
            'origin': 'http://127.0.0.1:5580', 'localStorage': [{'name': 'study-token', 'value': v.TOKEN}]}]}))
        v.BROWSER_SESSIONS.write_text('{"browsers": []}')
        self.capture('playwright-cli', "Browser 'challenge-source' closed")
        self.assertEqual(v.verify('cap_browser', self.root), 1)
        self.capture('playwright-cli', "Browser 'challenge-restored' closed")
        self.assertEqual(v.verify('cap_browser', self.root), 0)
        v.BROWSER_SESSIONS.write_text('{"browsers": [{"name": "challenge-restored"}]}')
        self.assertEqual(v.verify('cap_browser', self.root), 1)

    def test_csv_null_empty_distinction(self):
        (self.root / 'db_rows.txt').write_text('5\n')
        (self.root / 'roundtrip.csv').write_text(v.CSV_TEXT)
        v.DB_STATE.write_text(json.dumps(v.DB_ROWS))
        v.DB_ROUNDTRIP.write_text(json.dumps(v.DB_ROWS))
        self.assertEqual(v.verify('cap_db', self.root), 0)
        quoted_ids = re.sub(r'(?m)^([1-5]),', r'"\1",', v.CSV_TEXT)
        (self.root / 'roundtrip.csv').write_text(quoted_ids)
        self.assertEqual(v.verify('cap_db', self.root), 0)
        (self.root / 'roundtrip.csv').write_text(quoted_ids.replace('"1",', '"9",', 1))
        self.assertEqual(v.verify('cap_db', self.root), 1)
        (self.root / 'roundtrip.csv').write_text(quoted_ids)
        wrong = [dict(r) for r in v.DB_ROWS]
        wrong[3]['label'] = ''
        v.DB_ROUNDTRIP.write_text(json.dumps(wrong))
        self.assertEqual(v.verify('cap_db', self.root), 1)

    def test_graphql_uses_captured_correct_response(self):
        value = {'data': {'repository': {'nameWithOwner': 'example-owner/harmony',
            'defaultBranchRef': {'name': 'main', 'target': {'oid': v.HEAD,
                'parents': {'nodes': [{'oid': v.PARENT}]}}}}}}
        (self.root / 'github.json').write_text(json.dumps(value))
        self.assertEqual(v.verify('cap_gh', self.root), 1)
        self.capture('gh-github', value)
        self.assertEqual(v.verify('cap_gh', self.root), 0)


if __name__ == '__main__':
    unittest.main()
