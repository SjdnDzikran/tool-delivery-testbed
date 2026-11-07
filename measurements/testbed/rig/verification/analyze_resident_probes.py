#!/usr/bin/env python3
"""Summarize resident-token probes and compare them with the campaign; no model calls.

Usage, from the repository root:
  python3 measurements/testbed/rig/verification/analyze_resident_probes.py \
    PATH/TO/runtime/resident-probes-2026-11-06/main \
    PATH/TO/runtime/main-campaign-2026-11-01-v7 > \
    measurements/testbed/rig/verification/evidence/resident-probes-2026-11-06.json
Reads private request captures; prints counts and hashes only, without payloads.
"""
import collections
import csv
import glob
import hashlib
import json
import sys

MODES = ('eager', 'deferred', 'cli')
SERVERS = ('brave-search', 'github', 'playwright', 'postgres')
ALL = '+'.join(SERVERS)
ATTEMPTS = 'results/data/attempts.csv'


def first_request(pattern):
    return json.load(open(sorted(glob.glob(pattern))[0]))


def tools_hash(payload):
    tools = sorted(json.dumps(t, sort_keys=True) for t in payload.get('tools') or [])
    return hashlib.sha256('\n'.join(tools).encode()).hexdigest()


def system_hash(payload):
    first = (payload.get('input') or payload.get('messages'))[0]
    return hashlib.sha256(json.dumps(first, sort_keys=True).encode()).hexdigest()


def main(probes, campaign):
    rows = [json.loads(line) for line in open(f'{probes}/rows.jsonl')]
    counts = collections.defaultdict(set)
    for row in rows:
        counts[(row['model'], row['mode'], '+'.join(row['subset']))].add(row['first_request_input_tokens'])
    models = sorted({row['model'] for row in rows})
    baseline = {}
    summary = []
    for model in models:
        empty = {v for m in MODES for v in counts[(model, m, '')]}
        if len(empty) != 1:
            raise SystemExit(f'Empty-catalog probes differ for {model}: {sorted(empty)}')
        baseline[model] = empty.pop()
        for (row_model, mode, subset), values in sorted(counts.items()):
            if row_model == model:
                summary.append({'model': model, 'mode': mode, 'subset': subset, 'capabilities': subset.count('+') + 1 if subset else 0,
                                'first_request_input_tokens': sorted(values),
                                'resident_tokens_above_baseline': sorted(v - baseline[model] for v in values)})
    delta = {(s['model'], s['mode'], s['subset']): s['resident_tokens_above_baseline'][0] for s in summary}

    overhead = {}
    servers = {}
    for model in models:
        pair = delta[(model, 'eager', 'github')] + delta[(model, 'eager', 'postgres')]
        overhead[model] = pair - delta[(model, 'eager', 'github+postgres')]
        servers[model] = {
            s: delta[(model, 'eager', s)] - (overhead[model] if s in ('github', 'postgres') else 0)
            for s in SERVERS}
    additive_errors = []
    for model in models:
        for s in summary:
            if s['model'] != model or s['mode'] != 'eager' or not s['subset']:
                continue
            members = s['subset'].split('+')
            fixed = overhead[model] if {'github', 'postgres'} & set(members) else 0
            additive_errors.append(s['resident_tokens_above_baseline'][0] - fixed - sum(servers[model][m] for m in members))

    parity = []
    for model in models:
        for mode in MODES:
            probe = first_request(f'{probes}/cells/{model}-{mode}-{ALL}-r1/logs/raw-requests/*.json')
            original = first_request(f'{campaign}/control_1-{model}-{mode}-full-r01/jobs/*/task__*/agent/raw-requests/*.json')
            parity.append({'model': model, 'mode': mode,
                           'tool_definitions_identical': tools_hash(probe) == tools_hash(original),
                           'system_message_identical': system_hash(probe) == system_hash(original)})

    control = []
    attempts = [r for r in csv.DictReader(open(ATTEMPTS)) if r['is_selected_v7'] == 'True' and r['task'] == 'control_1']
    for model in models:
        none = {int(r['first_assistant_input_tokens']) for r in attempts if r['model'] == model and r['catalog'] == 'required'}
        for mode in MODES:
            full = sorted({int(r['first_assistant_input_tokens']) for r in attempts
                           if r['model'] == model and r['catalog'] == 'full' and r['mode'] == mode})
            control.append({'model': model, 'mode': mode, 'campaign_control_1_empty': sorted(none), 'campaign_control_1_full': full,
                            'campaign_delta': sorted(v - min(none) for v in full),
                            'probe_delta': delta[(model, mode, ALL)]})

    print(json.dumps({
        'provenance': 'ours: 288 task-free Pi requests on 2026-11-06, provider-reported input of each single request',
        'prompt': 'Reply with exactly: OK. Do not call any tools.',
        'run_order': 'shuffled from seed 2026',
        'valid_probes': sum(row['valid'] for row in rows),
        'total_probes': len(rows),
        'recorded_tokens_input_plus_output': sum(r['first_request_input_tokens'] + r['usage']['output'] for r in rows),
        'baseline_empty_catalog_input_tokens': baseline,
        'eager_additive_model': {
            'mcp_resource_tools_tokens_when_github_or_postgres_loaded': overhead,
            'server_tokens_excluding_resource_tools': servers,
            'max_abs_error_across_eager_subsets': max(abs(e) for e in additive_errors)},
        'campaign_first_request_parity': parity,
        'campaign_control_1_comparison': control,
        'summary': summary,
        'rows': rows,
    }, indent=1))


if __name__ == '__main__':
    main(*sys.argv[1:3])
