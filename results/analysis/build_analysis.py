#!/usr/bin/env python3
"""Derive the result tables from run_components.csv; no model calls, no private data.

Usage, from the repository root, with SciPy installed:
  python results/analysis/build_analysis.py
Writes summary.json beside this file. Cost is API-equivalent, from the dated
reference prices below; it is not subscription expenditure.
"""
import collections
import csv
import itertools
import json
import math
from pathlib import Path
import random
import statistics

from scipy.stats import spearmanr

HERE = Path(__file__).resolve().parent
ATTEMPTS = HERE.parent / 'data/attempts.csv'
MODELS = ('gpt6luna', 'glm53flash')
CATALOGS = ('required', 'full')
MODES = ('eager', 'deferred', 'cli')
PAIRS = (('eager', 'deferred'), ('eager', 'cli'), ('deferred', 'cli'))
CONTROLS = ('control_1', 'control_2')
CORRECTED_TASKS = ('find_salient_file', 'release_management_workflow')
BOOTSTRAP = 10000
SEED = 2026
# USD per million tokens, standard tier, short context, accessed 2026-11-06:
# developers.openai.com/api/docs/pricing and docs.z.ai/guides/overview/pricing.
PRICES = {'gpt6luna': {'in': 0.10, 'read': 0.01, 'out': 0.50, 'write_30m': 0.125},
          'glm53flash': {'in': 0.15, 'read': 0.03, 'out': 0.50, 'write_30m': None}}
READ_RATIOS = (0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0)
WRITE_RATIOS = (1.0, 1.25, 1.5, 2.0)
INTS = ('T', 'R', 'R_native', 'R_delivery', 'I', 'I_uncached', 'I_cache_read', 'G', 'reasoning', 'I_D', 'I_D_declarations',
        'I_O', 'I_H', 'I_R_native', 'I_R_delivery', 'epsilon', 'tool_output_tokens_once', 'guidance_tokens_once',
        'discovery_only_requests', 'discovery_input')


def load():
    rows = []
    for row in csv.DictReader(open(HERE / 'run_components.csv')):
        for key in INTS:
            row[key] = int(row[key])
        row['cost_usd'] = float(row['cost_usd'])
        row['tokens'] = row['I'] + row['G']
        row['clean'] = row['clean_success'] == 'True'
        row['disclosures'] = json.loads(row['disclosures'])
        rows.append(row)
    return rows


def group(rows, *keys):
    table = collections.defaultdict(list)
    for row in rows:
        table[tuple(row[k] for k in keys)].append(row)
    return table


def ratio(rows, field):
    wins = sum(r['clean'] for r in rows)
    return sum(r[field] for r in rows) / wins if wins else None


def share(part, whole):
    return part / whole if whole else None




def median_metric(rows, field):
    return statistics.median(r[field] for r in rows)


def difference(by_task, tasks, a, b, kind, field):
    """Return the paired difference for one metric, or None if undefined."""
    if kind == 'median':
        return statistics.mean(median_metric(by_task[t][a], field) - median_metric(by_task[t][b], field) for t in tasks)
    left = ratio([r for t in tasks for r in by_task[t][a]], field)
    right = ratio([r for t in tasks for r in by_task[t][b]], field)
    return None if left is None or right is None else left - right


def permutation(by_task, a, b, kind, field):
    tasks = sorted(by_task)
    observed = difference(by_task, tasks, a, b, kind, field)
    extreme = total = 0
    for flips in itertools.product((False, True), repeat=len(tasks)):
        swapped = {t: {a: by_task[t][b] if f else by_task[t][a], b: by_task[t][a] if f else by_task[t][b]} for t, f in zip(tasks, flips)}
        value = difference(swapped, tasks, a, b, kind, field)
        if value is None:
            return observed, None, total + 1
        total += 1
        extreme += abs(value) >= abs(observed) - 1e-9
    return observed, extreme / total, total


def bootstrap(by_task, a, b, kind, field, rng):
    tasks = sorted(by_task)
    values, undefined = [], 0
    for _ in range(BOOTSTRAP):
        sample = [rng.choice(tasks) for _ in tasks]
        keyed = {i: by_task[t] for i, t in enumerate(sample)}
        value = difference(keyed, list(keyed), a, b, kind, field)
        if value is None:
            undefined += 1
        else:
            values.append(value)
    values.sort()
    return values[int(0.025 * len(values))], values[int(0.975 * len(values)) - 1], undefined


def holm(entries):
    ordered = sorted((e for e in entries if e['p'] is not None), key=lambda e: e['p'])
    running = 0.0
    for rank, entry in enumerate(ordered):
        running = max(running, min(1.0, (len(ordered) - rank) * entry['p']))
        entry['p_holm'] = running


def statistics_section(rows):
    rng = random.Random(SEED)
    metrics = (('median_tokens', 'median', 'tokens'), ('median_cost', 'median', 'cost_usd'),
               ('tokens_per_success', 'pooled', 'tokens'), ('cost_per_success', 'pooled', 'cost_usd'))
    dependent = [r for r in rows if r['task'] not in CONTROLS]
    results = []
    for model in MODELS:
        entries = []
        for catalog, (a, b), (name, kind, field) in itertools.product(CATALOGS, PAIRS, metrics):
            by_task = collections.defaultdict(lambda: collections.defaultdict(list))
            for row in dependent:
                if row['model'] == model and row['catalog'] == catalog:
                    by_task[row['task']][row['mode']].append(row)
            observed, p, exchanges = permutation(by_task, a, b, kind, field)
            low, high, undefined = bootstrap(by_task, a, b, kind, field, rng)
            entries.append({'model': model, 'catalog': catalog, 'pair': f'{a}-{b}', 'metric': name, 'difference': observed,
                            'p': p, 'exchanges': exchanges, 'ci95': [low, high], 'undefined_resamples': undefined})
        holm(entries)
        results += entries
    return results


def pooled_views(rows):
    views = []
    subsets = {'tool_dependent': lambda r: r['task'] not in CONTROLS, 'controls': lambda r: r['task'] in CONTROLS,
               'single': lambda r: r['workload_group'] == 'single_capability', 'composite': lambda r: r['workload_group'] == 'composite'}
    for name, test in subsets.items():
        for (model, catalog, mode), group_rows in sorted(group([r for r in rows if test(r)], 'model', 'catalog', 'mode').items()):
            prices = PRICES[model]
            I = sum(r['I'] for r in group_rows)
            views.append({
                'subset': name, 'model': model, 'catalog': catalog, 'mode': mode, 'runs': len(group_rows),
                'clean': sum(r['clean'] for r in group_rows), 'tokens': sum(r['tokens'] for r in group_rows), 'I': I,
                'G': sum(r['G'] for r in group_rows), 'cost_usd': sum(r['cost_usd'] for r in group_rows),
                'cost_no_cache_usd': (I * prices['in'] + sum(r['G'] for r in group_rows) * prices['out']) / 1e6,
                'cache_read_share': share(sum(r['I_cache_read'] for r in group_rows), I),
                'tokens_per_success': ratio(group_rows, 'tokens'), 'cost_per_success': ratio(group_rows, 'cost_usd'),
                'median_T': statistics.median(r['T'] for r in group_rows),
                'tokens_failed': sum(r['tokens'] for r in group_rows if not r['clean']),
                'cost_failed_usd': sum(r['cost_usd'] for r in group_rows if not r['clean']),
                'pass3_tasks': sum(all(r['clean'] for r in cell) for cell in group(group_rows, 'task').values()),
                'tasks': len(group(group_rows, 'task')),
                **{k: sum(r[k] for r in group_rows) for k in ('I_R_native', 'I_R_delivery', 'I_D', 'I_D_declarations', 'I_O', 'I_H', 'epsilon', 'T')}})
    return views


def cells(rows):
    table = []
    for (model, catalog, task, mode), group_rows in sorted(group(rows, 'model', 'catalog', 'task', 'mode').items()):
        tokens = [r['tokens'] for r in group_rows]
        table.append({'model': model, 'catalog': catalog, 'task': task, 'mode': mode, 'median_tokens': statistics.median(tokens),
                      'min_tokens': min(tokens), 'max_tokens': max(tokens), 'spread': max(tokens) / min(tokens),
                      'median_I': statistics.median(r['I'] for r in group_rows), 'median_T': statistics.median(r['T'] for r in group_rows),
                      'median_cost': statistics.median(r['cost_usd'] for r in group_rows), 'clean': sum(r['clean'] for r in group_rows),
                      'tokens_per_success': ratio(group_rows, 'tokens'), 'cost_per_success': ratio(group_rows, 'cost_usd')})
    return table


def delivery_cost(run, T):
    """Resident, disclosure, and discovery input at T requests, from Equation (token-saving)."""
    disclosed = sum(size * max(0, T - first + 1) for size, first in run['disclosures'])
    return T * run['R'], disclosed, run['discovery_input']


def saving_equation(rows):
    points, winners = [], []
    for (model, catalog, task), group_rows in sorted(group(rows, 'model', 'catalog', 'task').items()):
        T = statistics.median(r['T'] for r in group_rows)
        predicted, observed = {}, {}
        for mode, mode_rows in group(group_rows, 'mode').items():
            parts = [delivery_cost(r, T) for r in mode_rows]
            predicted[mode[0]] = statistics.median(sum(p) for p in parts)
            observed[mode[0]] = statistics.median(r['I'] for r in mode_rows)
        for other in ('deferred', 'cli'):
            points.append({'model': model, 'catalog': catalog, 'task': task, 'on_demand': other, 'T': T,
                           'predicted_saving': predicted['eager'] - predicted[other], 'observed_saving': observed['eager'] - observed[other]})
        winners.append({'model': model, 'catalog': catalog, 'task': task,
                        'predicted': min(predicted, key=predicted.get), 'observed': min(observed, key=observed.get),
                        'predicted_tokens': predicted, 'observed_tokens': observed})
    return points, winners


def equation_summary(points, winners, rows):
    def stats(items):
        saving = [p['observed_saving'] for p in items]
        predicted = [p['predicted_saving'] for p in items]
        return {'n': len(items), 'sign_agreement': sum((a > 0) == (b > 0) for a, b in zip(saving, predicted)),
                'spearman': spearmanr(predicted, saving).statistic, 'median_abs_error': statistics.median(abs(a - b) for a, b in zip(saving, predicted)),
                'observed_saving_sum': sum(saving), 'predicted_saving_sum': sum(predicted)}
    summary = {'all': stats(points)}
    for key, value in itertools.product(MODELS, ('deferred', 'cli')):
        summary[f'{key}-{value}'] = stats([p for p in points if p['model'] == key and p['on_demand'] == value])
    for catalog in CATALOGS:
        summary[catalog] = stats([p for p in points if p['catalog'] == catalog])
    relative = [abs(r['epsilon']) / r['I'] for r in rows]
    relative.sort()
    summary['epsilon'] = {'median_abs_share': statistics.median(relative), 'p95_abs_share': relative[int(0.95 * len(relative))],
                          'max_abs_share': relative[-1], 'pooled_abs_share': sum(abs(r['epsilon']) for r in rows) / sum(r['I'] for r in rows)}
    summary['assumptions'] = {k: sum(r[k] == 'True' for r in rows) for k in ('history_intact', 'system_fixed', 'tools_grow_only')}
    summary['winner_agreement'] = {'n': len(winners), 'agree': sum(w['predicted'] == w['observed'] for w in winners),
                                   'tool_dependent_n': sum(w['task'] not in CONTROLS for w in winners),
                                   'tool_dependent_agree': sum(w['predicted'] == w['observed'] for w in winners if w['task'] not in CONTROLS),
                                   'observed_counts': collections.Counter(w['observed'] for w in winners),
                                   'predicted_counts': collections.Counter(w['predicted'] for w in winners)}
    return summary


def break_even(rows):
    """Compare the resident reduction with the content each on-demand run disclosed."""
    out = []
    for (model, catalog, task), group_rows in sorted(group([r for r in rows if r['task'] not in CONTROLS], 'model', 'catalog', 'task').items()):
        modes = group(group_rows, 'mode')
        for other in ('deferred', 'cli'):
            disclosed = statistics.median(sum(size for size, _ in r['disclosures']) for r in modes[(other,)])
            out.append({'model': model, 'catalog': catalog, 'task': task, 'on_demand': other, 'delta_R': modes[('eager',)][0]['R'] - modes[(other,)][0]['R'],
                        'median_disclosed': disclosed})
    return out


def price_sweep(rows):
    grid = []
    dependent = [r for r in rows if r['task'] not in CONTROLS]
    for (model, catalog), group_rows in sorted(group(dependent, 'model', 'catalog').items()):
        prices = PRICES[model]
        by_mode = group(group_rows, 'mode')
        for read, write in itertools.product(READ_RATIOS, WRITE_RATIOS):
            cost = {}
            for (mode,), mode_rows in by_mode.items():
                total = sum(r['I_uncached'] * prices['in'] * write + r['I_cache_read'] * prices['in'] * read + r['G'] * prices['out'] for r in mode_rows) / 1e6
                cost[mode] = total / sum(r['clean'] for r in mode_rows)
            grid.append({'model': model, 'catalog': catalog, 'read_ratio': read, 'write_ratio': write,
                         'cheapest': min(cost, key=cost.get), 'cost_per_success': cost})
    return grid


def covariates(rows):
    out = []
    for (model, mode), group_rows in sorted(group(rows, 'model', 'mode').items()):
        out.append({'model': model, 'mode': mode,
                    'spearman_tool_output_tokens': spearmanr([r['tool_output_tokens_once'] for r in group_rows], [r['tokens'] for r in group_rows]).statistic,
                    'spearman_T_tokens': spearmanr([r['T'] for r in group_rows], [r['tokens'] for r in group_rows]).statistic,
                    'median_tool_output_once': statistics.median(r['tool_output_tokens_once'] for r in group_rows),
                    'median_guidance_once': statistics.median(r['guidance_tokens_once'] for r in group_rows),
                    'median_T': statistics.median(r['T'] for r in group_rows)})
    return out


def activations(rows):
    table = {r['cell_id']: r for r in csv.DictReader(open(HERE / 'run_activations.csv'))}
    out = collections.defaultdict(collections.Counter)
    for row in rows:
        record = table[row['cell_id']]
        key = f"{row['model']}|{row['mode']}|{'control' if row['task'] in CONTROLS else 'tool_dependent'}"
        for field in ('tool_search', 'skill_read', 'help', 'mcp_call', 'bash', 'missed_required', 'loaded_not_required'):
            out[key][field] += int(record[field])
        out[key]['runs'] += 1
        out[key]['discovery_only_requests'] += row['discovery_only_requests']
    return out


def task_components(rows):
    out = []
    for (model, catalog, mode), group_rows in sorted(group(rows, 'model', 'catalog', 'mode').items()):
        out.append({'model': model, 'catalog': catalog, 'mode': mode, 'tasks': {}})
        for (task,), cell in sorted(group(group_rows, 'task').items()):
            out[-1]['tasks'][task] = {k: statistics.median(r[k] for r in cell) for k in ('I_R_delivery', 'I_D', 'I_O', 'I_H', 'T')}
    return out


def first_attempt_comparison():
    """Clean successes and tokens by view, with the two corrected-instruction tasks apart."""
    attempts = list(csv.DictReader(open(ATTEMPTS)))
    out = {}
    for group_name, in_group in (('corrected_tasks', True), ('other_tasks', False)):
        for view, flag in (('reported', 'is_selected_v7'), ('first', 'is_first_model_attempt')):
            for mode in MODES:
                subset = [r for r in attempts if r[flag] == 'True' and r['mode'] == mode and (r['task'] in CORRECTED_TASKS) == in_group]
                out[f'{group_name}|{view}|{mode}'] = {
                    'runs': len(subset),
                    'clean': sum(r['clean_success'] == 'True' for r in subset),
                    'tokens': sum(int(r['recorded_tokens']) for r in subset),
                }
    return out


def main():
    rows = load()
    points, winners = saving_equation(rows)
    cell_table = cells(rows)
    spreads = sorted(c['spread'] for c in cell_table)
    by_group = {}
    for model, catalog, mode in itertools.product(MODELS, CATALOGS, MODES):
        subset = [c['spread'] for c in cell_table if (c['model'], c['catalog'], c['mode']) == (model, catalog, mode)]
        by_group[f'{model}|{catalog}|{mode}'] = statistics.median(subset)
    first = [r for r in csv.DictReader(open(ATTEMPTS)) if r['is_first_model_attempt'] == 'True']
    summary = {
        'runs': len(rows), 'requests': sum(r['T'] for r in rows), 'prices_per_million_usd': PRICES,
        'total_cost_usd_by_model': {m: sum(r['cost_usd'] for r in rows if r['model'] == m) for m in MODELS},
        'cache_write_tokens_recorded': 0, 'auxiliary_records': 0, 'requests_above_272k': 0,
        'pooled': pooled_views(rows), 'cells': cell_table,
        'run_to_run_spread': {'median': statistics.median(spreads), 'p90': spreads[int(0.9 * len(spreads))], 'max': spreads[-1], 'by_group_median': by_group},
        'saving_points': points, 'saving_winners': winners, 'saving_summary': equation_summary(points, winners, rows),
        'statistics': statistics_section(rows), 'statistics_settings': {'bootstrap': BOOTSTRAP, 'seed': SEED, 'interval': 'percentile', 'alpha': 0.05, 'exchanges': 1024},
        'break_even': break_even(rows), 'price_sweep': price_sweep(rows), 'covariates': covariates(rows), 'activations': activations(rows),
        'task_components': task_components(rows), 'first_attempts': len(first), 'first_attempt_comparison': first_attempt_comparison(),
        'failures': [{k: r[k] for k in ('cell_id', 'task', 'model', 'catalog', 'mode', 'rep', 'outcome', 'T', 'tokens', 'cost_usd')} for r in rows if not r['clean']],
    }
    with open(HERE / 'summary.json', 'w') as handle:
        json.dump(summary, handle, indent=1, default=lambda o: dict(o) if hasattr(o, 'items') else str(o))
        handle.write('\n')


if __name__ == '__main__':
    main()
