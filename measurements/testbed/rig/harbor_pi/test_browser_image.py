"""Offline cache/provenance checks; no downloads or Docker calls."""
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from harbor_pi.browser_image import DownloadForm, SOURCE, install, reusable


class BrowserImageTests(unittest.TestCase):
    def test_cached_import_never_downloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = Path(tmp) / 'image.json'
            self.assertFalse(reusable(receipt, None))
            receipt.write_text(json.dumps({'source': SOURCE, 'image_id': 'sha256:example'}))
            with patch('harbor_pi.browser_image.image_id', return_value='sha256:example'), \
                    patch('harbor_pi.browser_image.urlopen') as network:
                install(receipt)
            network.assert_not_called()
            for current in (None, 'sha256:changed'):
                with self.assertRaises(RuntimeError):
                    reusable(receipt, current)
            receipt.unlink()
            with self.assertRaises(RuntimeError):
                reusable(receipt, 'sha256:unverified')

    def test_upstream_quota_does_not_start_docker_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = io.BytesIO(b'<form id="download-form" action="https://drive.usercontent.google.com/download">'
                               b'<input name="id" value="1See0ZhJRw0WTTL9y8hFlgaduwPZ_nGfd"></form>')
            blocked = io.BytesIO(b'<title>Google Drive - Quota exceeded</title>')
            blocked.headers = {'Content-Type': 'text/html'}
            receipt = Path(tmp) / 'image.json'
            with patch('harbor_pi.browser_image.image_id', return_value=None), \
                    patch('harbor_pi.browser_image.subprocess.check_output', return_value='/tmp'), \
                    patch('harbor_pi.browser_image.shutil.disk_usage', return_value=SimpleNamespace(free=30 * 1024**3)), \
                    patch('harbor_pi.browser_image.urlopen', side_effect=[first, blocked]), \
                    patch('harbor_pi.browser_image.subprocess.Popen') as launch:
                with self.assertRaisesRegex(RuntimeError, 'Quota exceeded'):
                    install(receipt)
            launch.assert_not_called()
            self.assertFalse(receipt.exists())
            record = json.loads(receipt.with_suffix('.blocked.json').read_text())
            self.assertFalse(record['archive_downloaded'])
            self.assertEqual(record['model_calls'], 0)

    def test_download_form_requires_upstream_file_and_host(self):
        html = ('<form id="download-form" action="https://drive.usercontent.google.com/download">'
                '<input name="id" value="1See0ZhJRw0WTTL9y8hFlgaduwPZ_nGfd">'
                '<input name="confirm" value="t"></form>')
        form = DownloadForm()
        form.feed(html)
        self.assertIn('confirm=t', form.url())
        for bad in (html.replace('drive.usercontent.google.com', 'example.org'),
                    html.replace('1See0ZhJRw0WTTL9y8hFlgaduwPZ_nGfd', 'other-file')):
            form = DownloadForm()
            form.feed(bad)
            with self.assertRaises(ValueError):
                form.url()


if __name__ == '__main__':
    unittest.main()
