#!/usr/bin/env python3
"""Compare whole-skill token sizes with root help; needs tiktoken, no model calls.

Run from the repository root:
  python3 measurements/testbed/rig/verification/measure_skill_help.py > \
    measurements/testbed/rig/verification/evidence/skill-help-sizes-2026-11-06.json
Root help for gh, playwright-cli and psql comes from the static receipts below;
bx comes from its captured v1.7.0 help file.
"""
import hashlib
import json
import re
from pathlib import Path

import tiktoken

ROOT = Path('measurements')
SKILLS = ROOT / 'testbed/rig/skills'
STATIC = ROOT / 'real-task-pilot-2026-10-31/cli-skills-static-v2.json'
BX_HELP = Path('docs/preliminary/skill-artifacts/bx-help-output.txt')
PICK = {'gh': '2.103.3', 'playwright-cli': '0.1.22', 'psql': '16.15'}
ENCODINGS = ('o200k_base', 'cl100k_base')


def bx_root_help():
    sections = re.split(r'(?m)^# bx ', BX_HELP.read_text())
    return sections[1].split('\n', 1)[1]


def main():
    static = {m['skill']: m for m in json.loads(STATIC.read_text())['measurements']}
    encoders = {name: tiktoken.get_encoding(name) for name in ENCODINGS}
    rows = []
    for folder in ('bx-search', 'gh', 'playwright-cli', 'psql'):
        text = (SKILLS / folder / 'SKILL.md').read_text()
        description = re.search(r'(?m)^description: (.*)$', text).group(1)
        name = re.search(r'(?m)^name: (.*)$', text).group(1)
        if folder == 'bx-search':
            help_text = bx_root_help()
            version = '1.7.0'
            help_tokens = {n: len(e.encode(help_text)) for n, e in encoders.items()}
            help_source = str(BX_HELP)
        else:
            version = PICK[folder]
            entry = next(h for h in static[folder]['historical_root_help']
                         if h['cli_version'] == version)
            help_tokens = entry['reference_tokens']
            help_source = str(STATIC)
        rows.append({
            'folder': folder, 'skill_name': name, 'cli_version': version,
            'skill_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'description_words': len(description.split()),
            'description_tokens': {n: len(e.encode(description)) for n, e in encoders.items()},
            'skill_tokens': {n: len(e.encode(text)) for n, e in encoders.items()},
            'root_help_tokens': help_tokens,
            'root_help_source': help_source,
        })
    print(json.dumps({
        'provenance': 'ours: static measurements, zero model calls',
        'reference_tokenizers_not_provider_token_measurements': True,
        'tiktoken_version': tiktoken.__version__,
        'count_scope': 'Entire SKILL.md including frontmatter, versus entire root help output',
        'measurements': rows,
    }, indent=2))


if __name__ == '__main__':
    main()
