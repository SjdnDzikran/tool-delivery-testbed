"""Offline input/reference separation and immutable-cache checks."""
import hashlib
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import unittest

from harbor_pi.real_task_inputs import gaia_instruction, postgres_fixtures, put


class RealTaskInputTests(unittest.TestCase):
    def test_reference_answer_never_enters_question_input(self):
        text = gaia_instruction({'question': 'Which city?',
                                 'reference_answer': 'SECRET_REFERENCE',
                                 'provenance': 'PRIVATE_PROVENANCE'}).decode()
        self.assertIn('Which city?', text)
        self.assertIn('answer.json', text)
        self.assertNotIn('SECRET_REFERENCE', text)
        self.assertNotIn('PRIVATE_PROVENANCE', text)

    def test_fixture_cache_is_checked_before_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'postgres-fixtures'
            root.mkdir()
            files = {}
            for name in ('employees.sql.gz', 'chinook.sql', 'LICENSE'):
                (root / name).write_bytes(b'fixture')
                files[name] = {'sha256': hashlib.sha256(b'fixture').hexdigest()}
            record = {'repository': 'neondatabase-labs/postgres-sample-dbs',
                      'commit': 'b54cb67534bf20775803b181b7a1c6f573422161', 'files': files}
            (root / 'receipt.json').write_text(json.dumps(record))
            with patch('harbor_pi.real_task_inputs.ROOT', Path(tmp)), \
                    patch('harbor_pi.real_task_inputs.urlopen') as network:
                self.assertEqual(postgres_fixtures(), record)
                (root / 'chinook.sql').write_bytes(b'changed')
                with self.assertRaises(ValueError):
                    postgres_fixtures()
            network.assert_not_called()

    def test_staged_assets_are_reused_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input/instruction.md'
            first = put(path, b'original')
            self.assertEqual(put(path, b'original'), first)
            with self.assertRaises(ValueError):
                put(path, b'changed')
            self.assertEqual(path.read_bytes(), b'original')


if __name__ == '__main__':
    unittest.main()
