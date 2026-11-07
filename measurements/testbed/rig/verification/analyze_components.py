#!/usr/bin/env python3
"""Attribute task-conversation input to the thesis input components; no model calls.

Reads private request payloads and session ledgers for the 432 reported runs and
writes numeric tables only, without payload text.

Components, per request, each item counted once per request where it appears:
  I_R  base instructions and resident definitions, from the provider-counted
       probes for the same model, configuration, and catalog
  I_D  on-demand guidance: tool_search results, skill and reference reads,
       command help, and tool declarations added after the first request
  I_O  all other tool results
  I_H  task instruction and earlier model output
  eps  provider-reported input minus the sum of the above

Message content is counted with tiktoken: o200k_base for GPT-6 Luna and
cl100k_base for GLM 5.3 Flash, whose tokenizer is not public. GPT-6 Luna reasoning
is encrypted in the payload, so its size comes from each turn's reported reasoning
tokens.

Usage, from the repository root, with tiktoken 0.14.0 installed:
  python analyze_components.py RUNTIME_DIR results/analysis
"""
import csv
import glob
import hashlib
import json
from pathlib import Path
import re
import sys

import tiktoken

ATTEMPTS = 'results/data/attempts.csv'
CATALOG = 'results/metadata/task_catalog.csv'
PROBES = 'measurements/testbed/rig/verification/evidence/resident-probes-2026-11-06.json'
ENCODING = {'gpt6luna': 'o200k_base', 'glm53flash': 'cl100k_base'}
SERVERS = ('brave-search', 'github', 'playwright', 'postgres')
SERVER_OF = {'brave_search': 'brave-search', 'github': 'github', 'playwright': 'playwright', 'postgres': 'postgres'}
SKILL_OF = {'bx-search': 'brave-search', 'gh': 'github', 'playwright-cli': 'playwright', 'psql': 'postgres'}
HELP = re.compile(r'(?:^|[\s;&|(])(?:--help|-h)(?:$|[\s;&|)])|\b(?:bx|gh|gh-github|playwright-cli|psql)\s+help\b|\bpsql\b.*\\\?')
PROBE_INSTRUCTION = 'Reply with exactly: OK. Do not call any tools.'


class Counter:
    def __init__(self, encoding):
        self.encoding = tiktoken.get_encoding(encoding)
        self.memo = {}

    def __call__(self, text):
        if not text:
            return 0
        key = hashlib.blake2b(text.encode('utf-8', 'surrogatepass'), digest_size=16).digest()
        if key not in self.memo:
            self.memo[key] = len(self.encoding.encode(text, disallowed_special=()))
        return self.memo[key]


def text_of(content):
    """Return the text of a message field and how many images it holds."""
    if content is None:
        return '', 0
    if isinstance(content, str):
        return content, 0
    texts, images = [], 0
    for part in content:
        if isinstance(part, str):
            texts.append(part)
        elif part.get('type') in ('input_image', 'image_url', 'image'):
            images += 1
        else:
            texts.append(part.get('text') or part.get('output_text') or '')
    return '\n'.join(texts), images


def normalize(payload):
    """Return (system, conversation items) in one format for both request APIs."""
    items = []
    if 'messages' in payload:
        system = payload['messages'][0]
        calls = {}
        for message in payload['messages'][1:]:
            role = message['role']
            if role == 'user':
                items.append(('user', text_of(message['content'])))
            elif role == 'assistant':
                text = text_of(message.get('content'))[0] + (message.get('reasoning_content') or '')
                for call in message.get('tool_calls') or []:
                    name, arguments = call['function']['name'], call['function']['arguments']
                    calls[call['id']] = (name, arguments)
                    text += name + arguments
                items.append(('model', (text, 0)))
            elif role == 'tool':
                items.append(('result', text_of(message['content']), calls.get(message.get('tool_call_id'), ('', ''))))
    else:
        system = payload['input'][0]
        calls = {}
        for item in payload['input'][1:]:
            kind = item.get('type') or item.get('role')
            if kind == 'user':
                items.append(('user', text_of(item['content'])))
            elif kind == 'reasoning':
                items.append(('reasoning', ('', 0)))
            elif kind == 'additional_tools':
                items.append(('declarations', (json.dumps(item['tools'], sort_keys=True), 0)))
            elif kind == 'function_call':
                calls[item['call_id']] = (item['name'], item['arguments'])
                items.append(('model', (item['name'] + item['arguments'], 0)))
            elif kind == 'function_call_output':
                items.append(('result', text_of(item.get('output')), calls.get(item['call_id'], ('', ''))))
            else:
                items.append(('model', text_of(item.get('content'))))
    return system, items


def tool_name(tool):
    return tool.get('name') or tool.get('function', {}).get('name')


def guidance_kind(name, arguments):
    """Classify a tool call that supplies guidance; None means an ordinary output."""
    if name == 'tool_search':
        return 'tool_search', None
    try:
        args = json.loads(arguments)
    except (TypeError, ValueError):
        return None, None
    if name == 'read' and '/skills/' in str(args.get('path', '')):
        match = re.search(r'/skills/([^/]+)/', args['path'])
        return 'skill_read', SKILL_OF.get(match.group(1)) if match else None
    if name == 'bash' and HELP.search(str(args.get('command', ''))):
        return 'help', None
    return None, None


def probe_tables():
    data = json.load(open(PROBES))
    resident = {(s['model'], s['mode'], s['subset']): s['first_request_input_tokens'][0] for s in data['summary']}
    return resident, data['baseline_empty_catalog_input_tokens']


def analyze_run(row, directory, resident, baseline, count, required_servers):
    ledger = json.load(open(f'{directory}/session-usage.json'))['records']
    paths = sorted(glob.glob(f'{directory}/raw-requests/payload-*.json'))
    if len(paths) != len(ledger):
        raise SystemExit(f"{row['cell_id']}: {len(paths)} payloads, {len(ledger)} ledger records")
    model, mode = row['model'], row['mode']
    subset = '+'.join(SERVERS) if row['catalog'] == 'full' else '+'.join(s for s in SERVERS if s in required_servers)
    instruction = count(PROBE_INSTRUCTION)
    R = resident[(model, mode, subset)] - instruction
    R_native = baseline[model] - instruction
    T = len(paths)
    totals = {'I': 0, 'I_uncached': 0, 'I_cache_read': 0, 'G': 0, 'reasoning': 0, 'cost_usd': 0.0,
              'I_D': 0, 'I_D_declarations': 0, 'I_O': 0, 'I_H': 0, 'images': 0}
    first_tools = None
    previous = None
    previous_system = None
    intact = system_fixed = tools_grow_only = True
    disclosures = {}
    declared = {}
    discovery_only = discovery_input = 0
    seen_results = 0
    results_final = []
    reasoning_before = 0
    for index, (path, record) in enumerate(zip(paths, ledger), 1):
        payload = json.load(open(path))
        usage = record['usage']
        reported = usage['input'] + usage['cacheRead'] + usage.get('cacheWrite', 0)
        totals['I'] += reported
        totals['I_uncached'] += usage['input']
        totals['I_cache_read'] += usage['cacheRead']
        totals['G'] += usage['output']
        totals['reasoning'] += usage.get('reasoning', 0)
        totals['cost_usd'] += usage['cost']['total']
        system, items = normalize(payload)
        if previous_system is not None and system != previous_system:
            system_fixed = False
        previous_system = system
        fingerprint = [hashlib.blake2b(json.dumps(i, sort_keys=True).encode(), digest_size=8).digest() for i in items]
        if previous is not None and fingerprint[:len(previous)] != previous:
            intact = False
        previous = fingerprint
        tools = {tool_name(t): t for t in payload.get('tools') or []}
        if first_tools is None:
            first_tools = set(tools)
        elif not first_tools <= set(tools):
            tools_grow_only = False
        for name, tool in tools.items():
            if name not in first_tools:
                size = count(json.dumps(tool, sort_keys=True))
                totals['I_D_declarations'] += size
                totals['I_D'] += size
                declared.setdefault(name, (size, index))
        new_results = []
        result_index = 0
        for item in items:
            kind, (text, images) = item[0], item[1]
            totals['images'] += images
            if kind == 'reasoning':
                continue
            if kind == 'declarations':
                size = count(text)
                totals['I_D'] += size
                totals['I_D_declarations'] += size
                declared.setdefault(text, (size, index))
                continue
            if kind == 'result':
                result_index += 1
                name, arguments = item[2]
                guidance, _ = guidance_kind(name, arguments)
                size = count(text)
                if guidance:
                    totals['I_D'] += size
                    disclosures.setdefault((name, result_index), (size, index))
                else:
                    totals['I_O'] += size
                if result_index > seen_results:
                    new_results.append(bool(guidance))
                if index == T:
                    results_final.append((size, guidance))
            else:
                totals['I_H'] += count(text)
        totals['I_H'] += reasoning_before if model == 'gpt6luna' else 0
        reasoning_before += usage.get('reasoning', 0)
        if new_results and all(new_results):
            discovery_only += 1
            discovery_input += reported
        seen_results = result_index
    I_R_total = T * R
    eps = totals['I'] - I_R_total - totals['I_D'] - totals['I_O'] - totals['I_H']
    output = {
        'cell_id': row['cell_id'], 'task': row['task'], 'workload_group': row['workload_group'], 'model': model,
        'catalog': row['catalog'], 'mode': mode, 'rep': row['rep'], 'outcome': row['outcome'],
        'clean_success': row['clean_success'], 'T': T, 'R': R, 'R_native': R_native, 'R_delivery': R - R_native,
        **{k: (round(v, 8) if k == 'cost_usd' else v) for k, v in totals.items()},
        'I_R_native': T * R_native, 'I_R_delivery': T * (R - R_native), 'epsilon': eps,
        'tool_output_tokens_once': sum(s for s, g in results_final if not g),
        'guidance_tokens_once': sum(s for s, g in results_final if g),
        'discovery_only_requests': discovery_only, 'discovery_input': discovery_input,
        'history_intact': intact, 'system_fixed': system_fixed, 'tools_grow_only': tools_grow_only,
        'disclosures': json.dumps(sorted(disclosures.values(), key=lambda x: x[1]) + sorted(declared.values(), key=lambda x: x[1])),
    }
    return output, activation_counts(payload, row, required_servers)


def activation_counts(payload, row, required_servers):
    """Count activations from the last request, which holds the whole conversation."""
    _, items = normalize(payload)
    counts = {'tool_search': 0, 'skill_read': 0, 'help': 0, 'mcp_call': 0, 'bash': 0, 'other_native': 0}
    loaded, used = set(), set()
    for item in items:
        if item[0] != 'result':
            continue
        name, arguments = item[2]
        text = item[1][0]
        kind, server = guidance_kind(name, arguments)
        if kind:
            counts[kind] += 1
        if kind == 'tool_search':
            loaded |= {SERVER_OF[s] for s in re.findall(r'mcp__([a-z_]+?)__', text) if s in SERVER_OF}
        if kind == 'skill_read' and server:
            loaded.add(server)
        if name.startswith('mcp__'):
            counts['mcp_call'] += 1
            server = SERVER_OF.get(name.split('__')[1])
            if server:
                used.add(server)
        elif name == 'bash':
            counts['bash'] += 1
        elif name and not kind and name != 'tool_search':
            counts['other_native'] += 1
    if row['mode'] == 'eager':
        missed = sorted(required_servers - used)
    else:
        missed = sorted(required_servers - loaded)
    unused_loaded = sorted(loaded - required_servers)
    return {'cell_id': row['cell_id'], **counts, 'loaded_or_used_servers': len(loaded | used),
            'missed_required': len(missed), 'missed_servers': '+'.join(missed),
            'loaded_not_required': len(unused_loaded)}


def main(runtime, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    catalog = {r['task']: r for r in csv.DictReader(open(CATALOG))}
    rows = [r for r in csv.DictReader(open(ATTEMPTS)) if r['is_selected_v7'] == 'True']
    resident, baseline = probe_tables()
    counters = {m: Counter(e) for m, e in ENCODING.items()}
    components, activations = [], []
    capabilities = {'brave': 'brave-search', 'github': 'github', 'browser': 'playwright', 'postgres': 'postgres'}
    for number, row in enumerate(rows, 1):
        directory = glob.glob(f"{runtime}/{row['source_phase']}/{row['cell_id']}/jobs/*/task__*/agent")[0]
        required = {capabilities[c] for c in re.split(r'[+;,| ]+', catalog[row['task']]['capabilities']) if c in capabilities}
        component, activation = analyze_run(row, directory, resident, baseline, counters[row['model']], required)
        components.append(component)
        activations.append(activation)
        if number % 50 == 0:
            print(number, flush=True)
    for name, table in (('run_components.csv', components), ('run_activations.csv', activations)):
        with open(out / name, 'w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(table[0]))
            writer.writeheader()
            writer.writerows(table)


if __name__ == '__main__':
    main(*sys.argv[1:3])
