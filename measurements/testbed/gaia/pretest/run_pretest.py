#!/usr/bin/env python3
"""No-search pretest of the two campaign GAIA questions. SPENDS MODEL TOKENS.

Runs after the campaign, so it checks the chosen questions and did not inform
their selection. Each run sends the question verbatim to Pi 1.0.4 with every
tool, MCP server, skill, and extension disabled. Writes results.csv beside this
file and private transcripts to OUT_DIR.

Usage, from the repository root: python3 measurements/testbed/gaia/pretest/run_pretest.py OUT_DIR
"""
import csv
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import tomllib

HERE = Path(__file__).resolve().parent
TESTBED = HERE.parents[1]
sys.path.insert(0, str(TESTBED / 'common'))
from verify_lib import answers_equal  # noqa: E402

PI = Path.home() / '.pi/research/node_modules/.bin/pi'
AUTH = Path.home() / '.pi/research/agent/auth.json'
MANIFEST = TESTBED / 'rig/examples/harbor-campaign.toml'
TASKS = tuple(sorted(p.stem for p in (TESTBED / 'gaia/gaia_tasks').glob('*.json')))  # operator-supplied
REPS = 3
SEED = 2026


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    models = tomllib.loads(MANIFEST.read_text())['models']
    tasks = {t: json.loads((TESTBED / f'gaia/gaia_tasks/{t}.json').read_text()) for t in TASKS}
    cells = [(t, m, r) for t in TASKS for m in sorted(models) for r in range(1, REPS + 1)]
    random.Random(SEED).shuffle(cells)
    rows = []
    for task, name, rep in cells:
        model = models[name]
        with tempfile.TemporaryDirectory() as agent:
            os.symlink(AUTH, Path(agent) / 'auth.json')
            env = {**os.environ, 'PI_CODING_AGENT_DIR': agent, 'PI_OFFLINE': '1', 'PI_SKIP_VERSION_CHECK': '1'}
            run = subprocess.run(
                [str(PI), '--mode', 'json', '--no-tools', '--no-mcp', '--no-skills', '--no-extensions',
                 '--no-context-files', '--no-prompt-templates', '--no-themes', '--no-approve', '--no-session',
                 '--provider', model['provider'], '--model', model['id'], '--thinking', model.get('thinking', 'max'),
                 '--', tasks[task]['question']],
                cwd=agent, env=env, capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL)
        (out / f'{task[:8]}-{name}-r{rep}.jsonl').write_text(run.stdout)
        answer, requested_tools = '', 0
        for line in run.stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            message = event.get('message') or {}
            if event.get('type') == 'message_end' and message.get('role') == 'assistant':
                parts = message.get('content') or []
                answer = ''.join(p.get('text', '') for p in parts if p.get('type') == 'text').strip()
                requested_tools += sum(p.get('type') == 'toolCall' for p in parts)
        reference = tasks[task]['reference_answer']
        rows.append({'task_id': task, 'model': name, 'rep': rep, 'raw_answer': answer,
                     'tool_dependent_pass': int(answers_equal(reference, answer)),
                     'reference_in_answer': int(reference.lower() in answer.lower()),
                     'exit_code': run.returncode, 'tool_calls': requested_tools})
        print(task[:8], name, rep, rows[-1]['tool_dependent_pass'], rows[-1]['reference_in_answer'],
              run.returncode, answer[:100].replace('\n', ' '), flush=True)
    with open(HERE / 'results.csv', 'w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: (r['task_id'], r['model'], r['rep'])))


if __name__ == '__main__':
    main(sys.argv[1])
