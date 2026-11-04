"""Verify a recorded execution freeze before launch; never include credentials."""
import hashlib
import importlib.metadata
import json
from pathlib import Path

import runner

RIG = Path(__file__).resolve().parents[1]


def execution_hashes():
    files = [RIG / 'runner.py']
    files.extend(p for p in (RIG / 'harbor_pi').rglob('*')
                 if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
    return {str(p.relative_to(RIG)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(files)}


def verify_freeze(manifest, manifest_path):
    reference = manifest['harness'].get('execution_freeze_receipt')
    if not reference:
        return  # Historical pilot profiles retain their own phase hash guards.
    path = (Path(manifest_path).resolve().parent / reference).resolve()
    receipt = json.loads(path.read_text())
    if (receipt.get('kind') != 'execution_freeze_not_launch_clearance'
            or receipt.get('manifest_sha256') != hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest()
            or receipt.get('resolved_manifest_digest') != runner.sha256_json(manifest)
            or receipt.get('execution_source_hashes') != execution_hashes()
            or receipt.get('harbor_version') != importlib.metadata.version('harbor')):
        raise ValueError('Execution freeze drift: stop; preserve attempts and create a reviewed new version')
