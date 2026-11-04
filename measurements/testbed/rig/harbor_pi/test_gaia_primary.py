"""Offline primary-source comparison, diagnostics and credential redirect checks."""
import unittest
from urllib.request import Request

from harbor_pi.gaia_primary import SafeRedirect, access_failure, compare


class GaiaPrimaryTests(unittest.TestCase):
    def test_comparison_requires_exact_official_question_answer_and_level(self):
        candidate = {'question': 'Which city?', 'reference_answer': 'Reference', 'provenance': {'level': '1'}}
        row = {'task_id': 'example', 'Question': 'Which city?', 'Final answer': 'Reference', 'Level': 1}
        result = compare([row], {'example': candidate})[0]
        self.assertTrue(all(v for k, v in result.items() if k != 'task_id'))
        for field in ['Question', 'Final answer', 'Level']:
            changed = dict(row, **{field: 'changed'})
            self.assertFalse(all(v for k, v in compare([changed], {'example': candidate})[0].items() if k != 'task_id'))
        self.assertFalse(compare([], {'example': candidate})[0]['official_record_present'])

    def test_gated_scope_and_missing_file_are_distinct(self):
        self.assertEqual(access_failure(403, b'Please enable access to public gated repositories'),
                         'token-needs-public-gated-read-permission')
        self.assertEqual(access_failure(404, b'Not found'), 'requested-file-or-revision-not-found')
        self.assertIn('account-gated', access_failure(403, b'Access is restricted'))

    def test_bearer_never_follows_cross_host_redirect(self):
        handler = SafeRedirect()
        req = Request('https://huggingface.co/example', headers={'Authorization': 'Bearer fake'})
        same = handler.redirect_request(req, None, 302, '', {}, 'https://huggingface.co/cache')
        self.assertEqual(same.get_header('Authorization'), 'Bearer fake')
        other = handler.redirect_request(req, None, 302, '', {}, 'https://cdn.example/file')
        self.assertIsNone(other.get_header('Authorization'))
        with self.assertRaises(ValueError):
            handler.redirect_request(req, None, 302, '', {}, 'http://example.org/file')


if __name__ == '__main__':
    unittest.main()
