"""Verify operator-supplied GAIA task files against authorized official Parquet.

Run directly with the isolated reader Python; no Harbor or model dependency.
Never accept access terms programmatically or disclose reference answers.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

RIG = Path(__file__).resolve().parents[1]
REVISION = '682dd723ee1e1697e00360edccf2366dc8418dd9'
URL = f'https://huggingface.co/datasets/gaia-benchmark/GAIA/resolve/{REVISION}/2023/validation/metadata.level1.parquet'


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(newurl).scheme != 'https':
            raise ValueError('Refuse an insecure official-data redirect')
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new and urlparse(req.full_url).netloc != urlparse(newurl).netloc:
            new.remove_header('Authorization')
        return new


def access_failure(status, body):
    text = body.decode('utf-8', 'replace').lower()
    if 'enable access to public gated' in text:
        return 'token-needs-public-gated-read-permission'
    if status == 403 and any(s in text for s in ('restricted', 'authorized', 'access request', 'accept')):
        return 'account-gated-access-or-token-authorization-required'
    if status == 404:
        return 'requested-file-or-revision-not-found'
    if status == 401:
        return 'authentication-required-or-token-invalid'
    return 'http-access-failure; inspect account permissions'


def compare(rows, candidates):
    by_id = {row['task_id']: row for row in rows}
    checks = []
    for task_id, candidate in candidates.items():
        row = by_id.get(task_id)
        checks.append({'task_id': task_id,
                       'candidate_sha256': hashlib.sha256(json.dumps(candidate, sort_keys=True).encode()).hexdigest(),
                       'official_record_present': row is not None,
                       'question_equal': bool(row and row['Question'] == candidate['question']),
                       'reference_equal': bool(row and str(row['Final answer']) == candidate['reference_answer']),
                       'level_equal': bool(row and str(row['Level']) == str(candidate['provenance']['level']))})
    return checks


def verify(token_file, output, task_files):
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    report = {'source': URL, 'revision': REVISION, 'model_calls': 0, 'verified': False}
    token = token_file.read_text().strip()
    try:
        request = Request(URL, headers={'Authorization': 'Bearer ' + token})
        try:
            with build_opener(SafeRedirect()).open(request, timeout=60) as response:
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024 or not raw.startswith(b'PAR1') or not raw.endswith(b'PAR1'):
                    raise ValueError('Unexpected official level-1 Parquet response')
        except HTTPError as exc:
            body = exc.read(16384)
            report.update(http_status=exc.code, error_kind=access_failure(exc.code, body),
                          response_excerpt_sha256=hashlib.sha256(body).hexdigest())
            return report
        path = output / 'metadata.level1.parquet'
        path.write_bytes(raw)
        path.chmod(0o600)
        report.update(metadata_bytes=len(raw), metadata_sha256=hashlib.sha256(raw).hexdigest())
        import duckdb
        connection = duckdb.connect(':memory:')
        try:
            result = connection.execute('SELECT * FROM read_parquet(?)', [str(path)])
            columns = [column[0] for column in result.description]
            rows = [dict(zip(columns, row)) for row in result.fetchall()]
        finally:
            connection.close()
        candidates = {}
        for source in task_files:
            candidate = json.loads(source.read_text())
            task_id = candidate['task_id']
            if task_id in candidates:
                raise ValueError('Duplicate task_id in supplied GAIA task files')
            candidates[task_id] = candidate
        if not candidates:
            raise ValueError('Supply at least one authorized GAIA task file')
        checks = compare(rows, candidates)
        report['checks'] = checks
        # Keep the authorized source private. Public evidence contains only hashes/matches.
        selected = [row for row in rows if row['task_id'] in candidates]
        private = output / 'selected-official-records.json'
        private.write_text(json.dumps(selected, indent=2) + '\n')
        private.chmod(0o600)
        report['verified'] = all(all(row[k] for k in ('official_record_present', 'question_equal', 'reference_equal', 'level_equal')) for row in checks)
        return report
    except Exception as exc:
        report['error_kind'] = type(exc).__name__
        raise
    finally:
        token = None
        token_file.unlink(missing_ok=True)
        (output / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--token-file', type=Path, required=True)
    parser.add_argument('--task', type=Path, action='append', required=True,
                        help='authorized task JSON; repeat for multiple tasks')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.token_file, args.output, args.task)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['verified'] else 1)
