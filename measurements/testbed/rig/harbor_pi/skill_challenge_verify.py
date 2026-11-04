"""Separate, offline verifier for the CLI-only skill challenge phase [ours]."""
import csv
import json
from pathlib import Path
import sys

TRACE_ROOT = Path('/logs/agent/cli-traces')
DB_STATE = Path('/home/study/db-state.json')
DB_ROUNDTRIP = Path('/home/study/db-csv-roundtrip.json')
BROWSER_SESSIONS = Path('/home/study/browser-sessions.json')
TOKEN = 'pilot-browser-click-verified-2037'
# Synthetic fixture values; replace with the expected target for your own run.
HEAD = 'f348e7689f5f0599b7cfef7de6d6a597a57615c7'
PARENT = '3efbf742533a375fc148d75513597e139329578b'
CSV_TEXT = 'id,label\n1,"comma, inside"\n2,"double ""quote"""\n3,"line one\nline two"\n4,\n5,""\n'
DB_ROWS = [dict(id=i, label=v) for i, v in enumerate(
    ['comma, inside', 'double "quote"', 'line one\nline two', None, ''], 1)]


def outputs(program):
    for path in sorted(TRACE_ROOT.glob('*.json')):
        meta = json.loads(path.read_text())
        if meta.get('program') == program and meta.get('returncode') == 0:
            text = path.with_suffix('.stdout').read_text().strip()
            try:
                value = json.loads(text)
            except ValueError:
                value = text
            yield value


def github_fields(value):
    repo = value['data']['repository']
    branch = repo['defaultBranchRef']
    commit = branch['target']
    return (repo['nameWithOwner'], branch['name'], commit['oid'],
            [p['oid'] for p in commit['parents']['nodes']])


def verify(task, root):
    root = Path(root)
    if task == 'cap_brave':
        artifact = json.loads((root / 'brave.json').read_text())
        for response in outputs('bx'):
            if not isinstance(response, dict) or not isinstance(response.get('web'), dict):
                continue
            q = response.get('query', {})
            results = response['web'].get('results', [])
            if (q.get('original') == 'Universitas Gadjah Mada official website'
                    and q.get('country', '').lower() == 'id'
                    and q.get('spellcheck_off') is True and len(results) == 1):
                if artifact == {k: results[0][k] for k in ('url', 'title')}:
                    return 0
        return 1
    if task == 'cap_browser':
        state = json.loads((root / 'browser-state.json').read_text())
        storage = [x for origin in state['origins']
                   if origin['origin'] == 'http://127.0.0.1:5580'
                   for x in origin['localStorage']]
        closed = set()
        for out in outputs('playwright-cli'):
            text = out.get('result', '') if isinstance(out, dict) else out
            for name in ('challenge-source', 'challenge-restored'):
                if text == f"Browser '{name}' closed":
                    closed.add(name)
        good = ((root / 'token.txt').read_text().strip() == TOKEN
                and {'name': 'study-token', 'value': TOKEN} in storage
                and json.loads(BROWSER_SESSIONS.read_text()) == {'browsers': []}
                and closed == {'challenge-source', 'challenge-restored'})
    elif task == 'cap_db':
        # PostgreSQL checks CSV semantics, including NULL versus quoted empty.
        # Byte equality incorrectly rejects valid FORCE_QUOTE exports.
        with (root / 'roundtrip.csv').open(newline='') as source:
            reader = csv.reader(source)
            header = next(reader, None)
            ids = [int(row[0]) for row in reader]
        good = ((root / 'db_rows.txt').read_text().strip() == '5'
                and header == ['id', 'label'] and ids == [1, 2, 3, 4, 5]
                and json.loads(DB_STATE.read_text()) == DB_ROWS
                and json.loads(DB_ROUNDTRIP.read_text()) == DB_ROWS)
    elif task == 'cap_gh':
        artifact = json.loads((root / 'github.json').read_text())
        good = (github_fields(artifact) == ('example-owner/harmony', 'main', HEAD, [PARENT])
                and any(artifact == value for value in outputs('gh-github')))
    else:
        raise ValueError(f'Unsupported skill challenge: {task}')
    return 0 if good else 1


if __name__ == '__main__':
    try:
        code = verify(sys.argv[1], sys.argv[2])
    except FileNotFoundError:
        code = 3
    except (ValueError, KeyError, TypeError, IndexError):
        code = 1
    except Exception:
        code = 4
    print(json.dumps({'task': sys.argv[1], 'exit_code': code}))
    sys.exit(code)
