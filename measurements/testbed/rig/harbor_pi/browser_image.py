"""Import the upstream Shopping Admin image once, without retaining its tar.

Setup only: no model calls. Keep the shared image; Harbor deletes trial state.
"""
from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen

import runner
from harbor_pi.bridge import RIG, docker_env

IMAGE = 'shopping_admin_final_0719:latest'
SOURCE = 'https://drive.google.com/uc?export=download&id=1See0ZhJRw0WTTL9y8hFlgaduwPZ_nGfd'
RECEIPT = RIG / 'runtime/real-task-preparation/shopping-admin-image.json'
GIB = 1024 ** 3


class DownloadForm(HTMLParser):
    def __init__(self):
        super().__init__()
        self.action = None
        self.fields = {}
        self.inside = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form' and attrs.get('id') == 'download-form':
            self.action = attrs.get('action')
            self.inside = True
        elif tag == 'input' and self.inside and attrs.get('name'):
            self.fields[attrs['name']] = attrs.get('value', '')

    def handle_endtag(self, tag):
        if tag == 'form':
            self.inside = False

    def url(self):
        parsed = urlparse(self.action or '')
        if (parsed.scheme, parsed.hostname, parsed.path) != (
                'https', 'drive.usercontent.google.com', '/download'):
            raise ValueError('Unexpected Google Drive download form')
        if self.fields.get('id') != '1See0ZhJRw0WTTL9y8hFlgaduwPZ_nGfd':
            raise ValueError('Unexpected Google Drive file identity')
        return self.action + '?' + urlencode(self.fields)


def image_id(image=None):
    result = subprocess.run(['docker', 'image', 'inspect', image or IMAGE, '--format', '{{.Id}}'],
                            env=docker_env(), capture_output=True, text=True)
    if result.returncode:
        # Distinguish a missing image from an unavailable daemon.
        subprocess.run(['docker', 'info', '--format', '{{.Driver}}'], env=docker_env(),
                       check=True, capture_output=True)
        return None
    return result.stdout.strip()


def reusable(receipt, current):
    if not current:
        if receipt.exists():
            raise RuntimeError('Previously imported image is missing; refuse automatic redownload')
        return False
    if not receipt.exists():
        raise RuntimeError('Existing image has no provenance receipt; refuse replacement or unverified reuse')
    record = json.loads(receipt.read_text())
    if record.get('source') != SOURCE or record.get('image_id') != current:
        raise RuntimeError('Cached image identity differs from its receipt')
    return True


def install(receipt=RECEIPT):
    receipt = Path(receipt)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    if reusable(receipt, image_id()):
        print('Reusing pinned Shopping Admin image; no download')
        return
    root = subprocess.check_output(['docker', 'info', '--format', '{{.DockerRootDir}}'],
                                   env=docker_env(), text=True).strip()
    filesystems = [RIG, Path(root), Path(tempfile.gettempdir())]
    free = lambda: min(shutil.disk_usage(p).free for p in filesystems)
    before = free()
    if before < 18 * GIB:
        raise RuntimeError('Need at least 18 GiB free before attempting this large import')
    # Lock beside the receipt: never start two downloads/imports for the same cache.
    import fcntl
    with receipt.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if reusable(receipt, image_id()):
            return
        with urlopen(SOURCE, timeout=60) as page:
            form = DownloadForm()
            form.feed(page.read(65536).decode('utf-8'))
        with urlopen(form.url(), timeout=120) as source:
            if 'text/html' in source.headers.get('Content-Type', ''):
                body = source.read(65536)
                title = re.search(rb'<title>(.*?)</title>', body, re.DOTALL | re.IGNORECASE)
                reason = title[1].decode('utf-8', 'replace') if title else 'Unexpected HTML'
                runner.atomic_write_json(receipt.with_suffix('.blocked.json'), {
                    'source': SOURCE, 'reason': reason, 'model_calls': 0,
                    'image_import_started': False, 'archive_downloaded': False,
                    'response_excerpt_sha256': hashlib.sha256(body).hexdigest(),
                    'observed_at': runner.zulu(runner.now_utc()),
                })
                raise RuntimeError(f'Image download blocked: {reason}; no archive imported')
            expected = source.headers.get('Content-Length')
            digest, size = hashlib.sha256(), 0
            done, low = threading.Event(), threading.Event()
            minimum = [before]
            logpath = receipt.with_suffix('.import.log')
            with logpath.open('xb') as log:
                proc = subprocess.Popen(['docker', 'image', 'load'], stdin=subprocess.PIPE,
                                        stdout=log, stderr=subprocess.STDOUT, env=docker_env())
                def guard():
                    while not done.wait(1):
                        try:
                            available = free()
                            minimum[0] = min(minimum[0], available)
                            if available < 2 * GIB:
                                low.set()
                                proc.terminate()
                                return
                        except OSError:
                            low.set()
                            proc.terminate()
                            return
                watcher = threading.Thread(target=guard, daemon=True)
                watcher.start()
                try:
                    while chunk := source.read(1024 * 1024):
                        proc.stdin.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                    proc.stdin.close()
                    rc = proc.wait(timeout=900)
                    if low.is_set():
                        raise RuntimeError('Import stopped to preserve 2 GiB free space; inspect Docker state')
                    if rc or not size or (expected and size != int(expected)):
                        raise RuntimeError('Incomplete/failed image import; diagnostic log retained')
                finally:
                    done.set()
                    if proc.poll() is None:
                        proc.terminate()
                        try:
                            proc.wait(timeout=30)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.wait()
                    if not proc.stdin.closed:
                        proc.stdin.close()
                    watcher.join()
        identity = image_id()
        if not identity:
            raise RuntimeError('Import did not produce the expected Shopping Admin image')
        runner.atomic_write_json(receipt, {
            'source': SOURCE, 'image': IMAGE, 'image_id': identity,
            'archive_sha256': digest.hexdigest(), 'archive_bytes': size,
            'free_bytes_before': before, 'free_bytes_after': free(),
            'minimum_observed_free_bytes': minimum[0], 'tar_retained': False,
            'imported_at': runner.zulu(runner.now_utc()),
        })
        print('Imported and pinned', identity, '; archive bytes', size, '; no tar retained')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if not args.execute:
        parser.error('--execute required: imports a large shared Docker image')
    import signal
    def interrupted(signum, frame):
        raise SystemExit(f'Import interrupted by signal {signum}; inspect retained diagnostics')
    signal.signal(signal.SIGTERM, interrupted)
    install()
