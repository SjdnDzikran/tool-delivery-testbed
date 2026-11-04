import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harbor_pi import github_tasks as gh


class GitHubTaskBoundaries(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.env=patch.dict('os.environ', {'GITHUB_EVAL_ORG':'test-owner'})
        self.env.start();self.addCleanup(self.env.stop)
        self.repo=gh.repository_for(self.root/'attempt')

    def test_fixed_length_unique_repository_names(self):
        self.assertRegex(self.repo,r'^test-owner/pi-[0-9a-f]{20}$')
        self.assertNotEqual(self.repo,gh.repository_for(self.root/'different'))

    @patch.object(gh,'api',return_value={'login':'personal-user'})
    def test_wrong_account_never_mutates(self,api):
        with self.assertRaises(ValueError):gh.provision('find_salient_file',self.repo,self.root/'receipt.json')
        self.assertEqual(api.call_count,1)
        self.assertEqual(api.call_args.args[0],'GET')

    @patch.object(gh,'api',side_effect=[{'login':gh.evaluation_owner()},{'id':42}])
    @patch.object(gh,'cached_base')
    def test_existing_repository_never_reset(self,cache,api):
        with self.assertRaises(ValueError):gh.provision('find_salient_file',self.repo,self.root/'receipt.json')
        cache.assert_not_called()
        self.assertTrue(all(call.args[0]=='GET' for call in api.call_args_list))

    @patch.object(gh,'git')
    @patch.object(gh,'cached_base',return_value=Path('/fixture-cache'))
    @patch.object(gh,'api')
    def test_created_id_recorded_before_seed(self,api,cache,git):
        sha=gh.BASES['find_salient_file'][1]
        api.side_effect=[{'login':gh.evaluation_owner()},None,{'id':42},{},{'sha':sha},[]]
        receipt=self.root/'receipt.json'
        git.side_effect=lambda args:self.assertEqual(json.loads(receipt.read_text())['repository_id'],42)
        gh.provision('find_salient_file',self.repo,receipt)
        self.assertNotIn('/fixture-cache',receipt.read_text())

    @patch.object(gh,'api')
    @patch.object(gh,'git')
    def test_cleanup_requires_recorded_id_and_marker(self,git,api):
        p=self.root/'receipt.json'
        p.write_text(json.dumps({'repository':self.repo,'repository_id':42,'marker':'owned','base_repository':'harmony'}))
        api.return_value={'id':99,'description':'owned','private':True}
        with self.assertRaises(ValueError):gh.archive_and_delete(p,self.root/'final',expected_repository=self.repo)
        git.assert_not_called()
        self.assertEqual(api.call_count,1)
        self.assertEqual(api.call_args.args[0],'GET')
        self.assertFalse((self.root/'final').exists())

    @patch.object(gh,'api')
    def test_cleanup_never_follows_a_foreign_receipt(self,api):
        p=self.root/'receipt.json'
        p.write_text(json.dumps({'repository':'foreign-owner/harmony'}))
        with self.assertRaises(ValueError):gh.archive_and_delete(p,self.root/'final',expected_repository=self.repo)
        api.assert_not_called()


if __name__=='__main__':unittest.main()
