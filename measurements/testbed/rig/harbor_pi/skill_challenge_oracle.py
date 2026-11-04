"""Zero-model positive controls; never used as a measured model agent."""
import json
from harbor.agents.base import AgentCapabilities
from harbor_pi.adapter import PiAgent

SCRIPTS = {
    'cap_brave': '''bx web 'Universitas Gadjah Mada official website' --country id --safesearch strict --spellcheck false --extra-snippets false --count 1 > response.json
python3 - <<'PY'
import json
from pathlib import Path
r=json.loads(Path('response.json').read_text())['web']['results'][0]
Path('artifacts/brave.json').write_text(json.dumps({k:r[k] for k in ('url','title')})+'\\n')
PY
''',
    'cap_browser': '''P=playwright-cli
$P -s=challenge-source open http://127.0.0.1:5580/ --browser chrome
$P -s=challenge-source eval '() => document.querySelector("#reveal").click()'
$P -s=challenge-source eval '() => localStorage.setItem("study-token", document.querySelector("#answer").textContent)'
$P -s=challenge-source state-save artifacts/browser-state.json
$P -s=challenge-source close
$P -s=challenge-restored open http://127.0.0.1:5580/ --browser chrome
$P -s=challenge-restored state-load artifacts/browser-state.json
$P -s=challenge-restored goto http://127.0.0.1:5580/
$P -s=challenge-restored --json localstorage-get study-token > restored.json
$P -s=challenge-restored close
python3 - <<'PY'
import json
from pathlib import Path
r=json.loads(Path('restored.json').read_text())['result']
assert r.startswith('study-token=')
Path('artifacts/token.txt').write_text(r.partition('=')[2]+'\\n')
PY
''',
    'cap_db': '''cat > input.csv <<'CSV'
id,label
1,"comma, inside"
2,"double ""quote"""
3,"line one
line two"
4,
5,""
CSV
psql -X -w -v ON_ERROR_STOP=1 "$TESTBED_PG_DSN" -c 'CREATE TABLE smoke_items(id integer PRIMARY KEY,label text)'
psql -X -w -v ON_ERROR_STOP=1 "$TESTBED_PG_DSN" -c "\\copy smoke_items FROM 'input.csv' WITH (FORMAT csv, HEADER true)"
psql -X -w -v ON_ERROR_STOP=1 "$TESTBED_PG_DSN" -c "\\copy (SELECT id,label FROM smoke_items ORDER BY id) TO 'artifacts/roundtrip.csv' WITH (FORMAT csv, HEADER true)"
psql -X -w -v ON_ERROR_STOP=1 "$TESTBED_PG_DSN" -Atqc 'SELECT count(*) FROM smoke_items' > artifacts/db_rows.txt
''',
    'cap_gh': '''query='query($owner:String!,$name:String!,$first:Int!){repository(owner:$owner,name:$name){nameWithOwner defaultBranchRef{name target{... on Commit{oid parents(first:$first){nodes{oid}}}}}}}'
gh-github api graphql -f query="$query" -f owner="${TESTBED_GH_REPO%/*}" -f name="${TESTBED_GH_REPO#*/}" -F first=1 > artifacts/github.json
''',
}


class SkillChallengeOracle(PiAgent):
    capabilities = AgentCapabilities(atif=False)

    def __init__(self, *, recovery_csv=None, **kwargs):
        super().__init__(**kwargs)
        self.recovery_csv = recovery_csv
        if recovery_csv and self.spec['task'] != 'cap_db':
            raise ValueError('CSV recovery is database-only')

    @staticmethod
    def name():
        return 'skill-challenge-zero-model-oracle'

    async def run(self, instruction, environment, context):
        script = SCRIPTS[self.spec['task']]
        if self.recovery_csv:
            await environment.upload_file(self.recovery_csv, '/home/study/workspace/input.csv')
            script = '''psql -X -w -v ON_ERROR_STOP=1 "$TESTBED_PG_DSN" -c 'CREATE TABLE smoke_items(id integer PRIMARY KEY,label text)'
psql -X -w -v ON_ERROR_STOP=1 "$TESTBED_PG_DSN" -c "\\copy smoke_items FROM 'input.csv' WITH (FORMAT csv,HEADER true)"
cp input.csv artifacts/roundtrip.csv
psql -X -w -v ON_ERROR_STOP=1 "$TESTBED_PG_DSN" -Atqc 'SELECT count(*) FROM smoke_items' > artifacts/db_rows.txt
'''
        result = await self._exec(environment, 'set -eu\n. /home/study/.trial-env\n'
                                  'touch /logs/agent/events.jsonl\n' + script)
        (self.logs_dir / 'oracle-stdout.txt').write_text(result.stdout or '')
        (self.logs_dir / 'oracle-proof.json').write_text(json.dumps({
            'model_calls': 0, 'task': self.spec['task'], 'csv_recovery_only': bool(self.recovery_csv),
            'purpose': 'Check actual CLI operations, artifact transfer and separate verification',
        }) + '\n')
