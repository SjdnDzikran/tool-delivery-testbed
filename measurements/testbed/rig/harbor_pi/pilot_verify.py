"""Separate-container verifier for tiny engineering probes, not thesis tasks."""
import json
from pathlib import Path
import sys
from urllib.parse import urlparse


def verify(task, root):
    root = Path(root)
    names = {'cap_brave': 'brave.json', 'cap_browser': 'token.txt',
             'cap_db': 'db_rows.txt', 'cap_gh': 'github.txt'}
    path = root / names[task]
    if not path.is_file():
        return 3
    text = path.read_text().strip()
    if task == 'cap_brave':
        try:
            value = json.loads(text)
            good = (isinstance(value, dict) and set(value) == {'url', 'title'}
                    and isinstance(value['title'], str) and bool(value['title'].strip())
                    and isinstance(value['url'], str) and urlparse(value['url']).scheme in ('http', 'https')
                    and bool(urlparse(value['url']).netloc))
            provenance = Path('/opt/study/brave-provenance.json')
            if provenance.is_file():
                proof = json.loads(provenance.read_text())
                good = good and value in proof.get('observed_tops', [proof.get('top')])
            else:
                good = False
        except (ValueError, TypeError):
            good = False
    elif task == 'cap_browser':
        good = text == 'pilot-browser-click-verified-2037'
    elif task == 'cap_gh':
        good = text == 'f348e7689f5f0599b7cfef7de6d6a597a57615c7'
    else:
        state = Path('/home/study/db-state.json')
        good = (text == '2' and state.is_file() and json.loads(state.read_text()) ==
                [{'id': 1, 'label': 'alpha'}, {'id': 2, 'label': 'beta'}])
    return 0 if good else 1

if __name__ == '__main__':
    try:
        code = verify(sys.argv[1], sys.argv[2])
    except Exception:
        code = 4
    print(json.dumps({'task': sys.argv[1], 'exit_code': code}))
    sys.exit(code)
