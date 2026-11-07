#!/usr/bin/env python3
"""Count gh-github and plain gh shell use across reported runs; no model calls.

Usage, from the repository root:
  python3 measurements/testbed/rig/verification/audit_gh_wrapper.py \
    PATH/TO/runtime/main-campaign-2026-11-01-v7 > \
    measurements/testbed/rig/verification/evidence/gh-wrapper-usage-2026-11-06.json
Reads private native events; prints aggregate counts only, without commands.
Counts are text matches on shell commands, so a command in a loop counts once.
"""
import collections
import csv
import glob
import json
import re
import sys

SELECTED = 'results/data/selected_assignments.csv'
PLAIN = re.compile(r'(?<![\w./-])(?:/\S*/)?gh(?=\s+[a-z-])')
WRAPPER = re.compile(r'(?<![\w/-])gh-github\b')
VERSION_CHECK = re.compile(r'(?<![\w./-])gh\s+--version\b')
SKILL = '/skills/gh/'


def tool_calls(path):
    seen = set()
    for line in open(path, errors='replace'):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        message = event.get('message', {}) if event.get('type') == 'message_end' else {}
        if message.get('role') != 'assistant':
            continue
        for block in message.get('content') or []:
            if (isinstance(block, dict) and block.get('type') == 'toolCall'
                    and block.get('id') not in seen):
                seen.add(block.get('id'))
                yield block['name'], block.get('arguments', {})


def scan(path):
    result = collections.Counter()
    skill_read = False
    for name, arguments in tool_calls(path):
        if name == 'read' and SKILL in arguments.get('path', ''):
            skill_read = True
        if name != 'bash':
            continue
        command = arguments.get('command', '')
        if SKILL in command:
            skill_read = True
        wrapper = len(WRAPPER.findall(command))
        plain = len(PLAIN.findall(command))
        if (wrapper or plain) and 'first_use' not in result:
            result['first_use'] = 1
            result['skill_read_before_first_use'] = int(skill_read)
        result['wrapper'] += wrapper
        version_checks = len(VERSION_CHECK.findall(command))
        result['plain_operation'] += plain - version_checks
        result['plain_version_check'] += version_checks
    return result


def main(root):
    groups = collections.defaultdict(collections.Counter)
    for row in csv.DictReader(open(SELECTED)):
        paths = glob.glob(f"{root}/{row['cell_id']}/jobs/*/task__*/agent/events.jsonl")
        if len(paths) != 1:
            raise SystemExit(f"Expected one event log for {row['cell_id']}")
        counts = scan(paths[0])
        route = 'cli' if row['mode'] == 'cli' else 'mcp'
        need = 'requires_github' if 'github' in row['capabilities'] else 'no_github_required'
        group = groups[f'{route}_{need}']
        group['runs'] += 1
        group['runs_using_wrapper'] += int(counts['wrapper'] > 0)
        group['runs_with_plain_gh_operation'] += int(counts['plain_operation'] > 0)
        group['runs_with_plain_gh_version_check'] += int(counts['plain_version_check'] > 0)
        group['runs_reading_skill_before_first_use'] += counts['skill_read_before_first_use']
        group['wrapper_matches'] += counts['wrapper']
    print(json.dumps({
        'provenance': 'ours: offline text match over native events of the 432 reported runs',
        'model_calls': 0,
        'groups': {name: dict(sorted(values.items())) for name, values in sorted(groups.items())},
    }, indent=2))


if __name__ == '__main__':
    main(sys.argv[1])
