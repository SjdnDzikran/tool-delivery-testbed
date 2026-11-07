#!/usr/bin/env python3
"""Generate the thesis result figures as vector PDFs from committed numeric tables.

Usage, from the repository root, with matplotlib installed:
  python results/figures/build_figures.py
"""
import collections
import csv
import json
from pathlib import Path
import random
import statistics

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
ANALYSIS = ROOT / 'results/analysis'
SUMMARY = json.load(open(ANALYSIS / 'summary.json'))
PROBES = json.load(open(ROOT / 'measurements/testbed/rig/verification/evidence/resident-probes-2026-11-06.json'))
RUNS = list(csv.DictReader(open(ANALYSIS / 'run_components.csv')))
TASK_LABEL = {r['task']: r['task_label'] for r in csv.DictReader(open(ROOT / 'results/metadata/task_catalog.csv'))}
TASK_LABEL.update({t: l.title() for t, l in TASK_LABEL.items() if t in ('employee_demographics_report', 'employee_hierarchy_management', 'products_sales_analysis', 'customer_segmentation_setup', 'find_salient_file', 'release_management_workflow')})

MODELS = ('gpt6luna', 'glm53flash')
MODEL_NAME = {'gpt6luna': 'GPT-6 Luna', 'glm53flash': 'GLM 5.3 Flash'}
MODES = ('eager', 'deferred', 'cli')
MODE_NAME = {'eager': 'Eager MCP', 'deferred': 'Deferred MCP', 'cli': 'CLI plus skills'}
COLOR = {'eager': '#2a78d6', 'deferred': '#eb6834', 'cli': '#1baf7a'}
MARKER = {'eager': 'o', 'deferred': 's', 'cli': '^'}
INK, MUTED, GRID = '#0b0b0b', '#52514e', '#e4e3df'
WIDTH = 5.7

plt.rcParams.update({
    'font.family': 'serif', 'font.serif': ['STIXGeneral', 'DejaVu Serif'], 'mathtext.fontset': 'stix',
    'font.size': 9, 'axes.titlesize': 9, 'axes.labelsize': 9, 'legend.fontsize': 8, 'xtick.labelsize': 8, 'ytick.labelsize': 8,
    'pdf.fonttype': 42, 'axes.edgecolor': MUTED, 'axes.linewidth': 0.6, 'axes.spines.top': False, 'axes.spines.right': False,
    'axes.grid': True, 'grid.color': GRID, 'grid.linewidth': 0.5, 'axes.axisbelow': True, 'xtick.color': MUTED, 'ytick.color': MUTED,
    'text.color': INK, 'axes.labelcolor': INK, 'legend.frameon': False, 'savefig.bbox': 'tight', 'savefig.pad_inches': 0.03})


def save(figure, name):
    figure.savefig(OUT / f'{name}.pdf')
    plt.close(figure)


def mode_legend(figure, y=1.0):
    handles = [Line2D([], [], marker=MARKER[m], color=COLOR[m], linestyle='', markersize=6, label=MODE_NAME[m]) for m in MODES]
    figure.legend(handles=handles, loc='lower center', ncol=3, bbox_to_anchor=(0.5, y))


def thousands(value, _):
    return f'{value:,.0f}'


def resident_catalogs():
    figure, axes = plt.subplots(1, 2, figsize=(WIDTH, 2.7), sharey=True)
    rng = random.Random(2026)
    for axis, model in zip(axes, MODELS):
        for offset, mode in zip((-0.14, 0, 0.14), MODES):
            points = collections.defaultdict(list)
            for row in PROBES['summary']:
                if row['model'] == model and row['mode'] == mode and row['capabilities']:
                    points[row['capabilities']].append(row['resident_tokens_above_baseline'][0])
            xs = sorted(points)
            axis.plot(xs, [statistics.median(points[x]) for x in xs], color=COLOR[mode], linewidth=1.2, zorder=2)
            for x in xs:
                axis.scatter([x + offset + rng.uniform(-0.03, 0.03) for _ in points[x]], points[x], s=20, marker=MARKER[mode],
                             color=COLOR[mode], edgecolor='white', linewidth=0.5, zorder=3)
        axis.set_yscale('log')
        axis.set_xticks([1, 2, 3, 4])
        axis.set_title(MODEL_NAME[model])
        axis.set_xlabel('Capabilities in the catalog')
        axis.yaxis.set_major_formatter(FuncFormatter(thousands))
    axes[0].set_ylabel('Tokens added to every request')
    mode_legend(figure)
    figure.tight_layout()
    save(figure, 'resident-catalogs')


def eager_servers():
    tools = {'github': 46, 'brave-search': 8, 'playwright': 25, 'postgres': 9}
    names = {'github': 'GitHub', 'brave-search': 'Brave Search', 'playwright': 'Playwright', 'postgres': 'PostgreSQL'}
    sizes = PROBES['eager_additive_model']['server_tokens_excluding_resource_tools']
    order = ['postgres', 'playwright', 'brave-search', 'github']
    figure, axis = plt.subplots(figsize=(WIDTH, 1.9))
    for shift, model, color in ((0.2, 'gpt6luna', '#6250d6'), (-0.2, 'glm53flash', '#eda100')):
        values = [sizes[model][s] for s in order]
        axis.barh([i + shift for i in range(4)], values, height=0.36, color=color, label=MODEL_NAME[model])
        for i, value in enumerate(values):
            axis.text(value + 150, i + shift, f'{value:,}', va='center', fontsize=7.5, color=MUTED)
    axis.set_yticks(range(4), [f'{names[s]} ({tools[s]} tools)' for s in order], color=INK)
    axis.set_xlabel('Tokens added to every request under eager MCP')
    axis.xaxis.set_major_formatter(FuncFormatter(thousands))
    axis.grid(axis='y', visible=False)
    axis.set_xlim(0, 15500)
    handles, labels = axis.get_legend_handles_labels()
    axis.legend(handles[::-1], labels[::-1], loc='lower right')
    figure.tight_layout()
    save(figure, 'eager-servers')


def task_tokens():
    cells = SUMMARY['cells']
    reference = collections.defaultdict(list)
    for cell in cells:
        reference[cell['task']].append(cell['median_tokens'])
    order = sorted(reference, key=lambda t: statistics.median(reference[t]))
    figure, axes = plt.subplots(2, 2, figsize=(WIDTH, 6.0), sharex=True, sharey=True)
    for row, model in enumerate(MODELS):
        for column, catalog in enumerate(('required', 'full')):
            axis = axes[row][column]
            for offset, mode in zip((0.22, 0, -0.22), MODES):
                for cell in cells:
                    if (cell['model'], cell['catalog'], cell['mode']) == (model, catalog, mode):
                        y = order.index(cell['task']) + offset
                        axis.plot([cell['min_tokens'] / 1e3, cell['max_tokens'] / 1e3], [y, y], color=COLOR[mode], linewidth=0.9, solid_capstyle='round')
                        axis.scatter(cell['median_tokens'] / 1e3, y, s=16, marker=MARKER[mode], color=COLOR[mode], edgecolor='white', linewidth=0.4, zorder=3)
            axis.set_xscale('log')
            axis.set_title(f'{MODEL_NAME[model]}, {catalog} catalog')
            axis.xaxis.set_major_formatter(FuncFormatter(thousands))
            axis.set_yticks(range(len(order)), [TASK_LABEL[t] for t in order], color=INK)
            axis.grid(axis='y', visible=False)
    figure.supxlabel('Recorded tokens, thousands (log scale)', fontsize=9)
    mode_legend(figure)
    figure.tight_layout()
    save(figure, 'task-tokens')


def pooled(subset='tool_dependent'):
    return {(p['model'], p['catalog'], p['mode']): p for p in SUMMARY['pooled'] if p['subset'] == subset}


def six_positions(axis, labels=('E', 'D', 'C')):
    positions = [0, 1, 2, 3.6, 4.6, 5.6]
    axis.set_xticks(positions, list(labels) * 2, color=INK)
    axis.grid(axis='x', visible=False)
    return positions


def components():
    parts = (('I_R_native', 'Base resident', '#8e8c84'), ('I_R_delivery', 'Delivery resident', '#2a78d6'),
             ('I_D', 'On-demand guidance', '#eb6834'), ('I_O', 'Tool outputs', '#1baf7a'), ('I_H', 'Conversation', '#eda100'))
    views = pooled()
    figure, axes = plt.subplots(1, 2, figsize=(WIDTH, 2.9), sharey=True)
    for axis, model in zip(axes, MODELS):
        positions = six_positions(axis)
        keys = [(model, c, m) for c in ('required', 'full') for m in MODES]
        bottoms = [0.0] * 6
        for field, label, color in parts:
            values = [views[k][field] / 1e6 for k in keys]
            axis.bar(positions, values, bottom=bottoms, width=0.82, color=color, edgecolor='white', linewidth=0.8, label=label)
            bottoms = [b + v for b, v in zip(bottoms, values)]
        axis.set_title(MODEL_NAME[model])
        axis.set_xlabel('Required catalog' + ' ' * 10 + 'Full catalog')
    axes[0].set_ylabel('Task-conversation input, millions')
    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(handles[::-1], labels[::-1], loc='lower center', ncol=5, bbox_to_anchor=(0.5, 1.0), columnspacing=1.0, handlelength=1.0)
    figure.tight_layout()
    save(figure, 'input-components')


def saving_scatter():
    points = SUMMARY['saving_points']
    figure, axes = plt.subplots(1, 2, figsize=(WIDTH, 3.0), sharex=True, sharey=True)
    for axis, kind in zip(axes, ('deferred', 'cli')):
        limit = 3.5e3
        axis.plot([-300, limit], [-300, limit], color=MUTED, linewidth=0.8, zorder=1)
        axis.axhline(0, color=GRID, linewidth=0.8)
        axis.axvline(0, color=GRID, linewidth=0.8)
        for point in points:
            if point['on_demand'] != kind:
                continue
            filled = point['catalog'] == 'full'
            color = '#6250d6' if point['model'] == 'gpt6luna' else '#eda100'
            axis.scatter(point['predicted_saving'] / 1e3, point['observed_saving'] / 1e3, s=20, marker='o' if point['model'] == 'gpt6luna' else 'D',
                         facecolor=color if filled else 'white', edgecolor=color, linewidth=0.9, zorder=3)
        axis.set_xscale('symlog', linthresh=30)
        axis.set_yscale('symlog', linthresh=30)
        for setter in (axis.xaxis, axis.yaxis):
            setter.set_major_formatter(FuncFormatter(thousands))
        axis.set_xticks([-100, 0, 100, 1000])
        axis.set_yticks([-1000, -100, 0, 100, 1000])
        axis.set_title(f'Eager MCP against {MODE_NAME[kind]}')
        axis.set_xlabel('Predicted saving, thousand tokens')
    axes[0].set_ylabel('Observed saving, thousand tokens')
    handles = [Line2D([], [], marker='o', color='#6250d6', linestyle='', label='GPT-6 Luna'), Line2D([], [], marker='D', color='#eda100', linestyle='', label='GLM 5.3 Flash'),
               Line2D([], [], marker='o', markerfacecolor='#8e8c84', markeredgecolor='#8e8c84', linestyle='', label='Full catalog'),
               Line2D([], [], marker='o', markerfacecolor='white', markeredgecolor='#8e8c84', linestyle='', label='Required catalog'),
               Line2D([], [], color=MUTED, linewidth=0.8, label='Prediction equals observation')]
    figure.legend(handles=handles, loc='lower center', ncol=5, bbox_to_anchor=(0.5, 1.0), columnspacing=1.0, handletextpad=0.3)
    figure.tight_layout()
    save(figure, 'saving-prediction')


def cache_cost():
    views = pooled()
    figure, axes = plt.subplots(1, 2, figsize=(WIDTH, 2.6))
    for axis, model in zip(axes, MODELS):
        positions = six_positions(axis)
        keys = [(model, c, m) for c in ('required', 'full') for m in MODES]
        axis.bar([p - 0.2 for p in positions], [views[k]['cost_no_cache_usd'] for k in keys], width=0.38, color='#c9c8c2', label='All input at the uncached price')
        axis.bar([p + 0.2 for p in positions], [views[k]['cost_usd'] for k in keys], width=0.38, color='#2a78d6', label='Recorded cache reads applied')
        axis.set_title(MODEL_NAME[model])
        axis.set_xlabel('Required catalog' + ' ' * 10 + 'Full catalog')
        axis.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f'${v:.2f}' if v % 1 else f'${v:.0f}'))
    axes[0].set_ylabel('Reference cost, 30 runs')
    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(handles, labels, loc='lower center', ncol=2, bbox_to_anchor=(0.5, 1.0))
    figure.tight_layout()
    save(figure, 'cache-cost')


def price_sensitivity():
    published = {'gpt6luna': 0.10, 'glm53flash': 0.20}
    figure, axes = plt.subplots(2, 2, figsize=(WIDTH, 3.9), sharex=True, sharey=True)
    for row, model in enumerate(MODELS):
        for column, catalog in enumerate(('required', 'full')):
            axis = axes[row][column]
            grid = sorted((g for g in SUMMARY['price_sweep'] if g['model'] == model and g['catalog'] == catalog and g['write_ratio'] == 1.0), key=lambda g: g['read_ratio'])
            for mode in ('eager', 'deferred'):
                axis.plot([g['read_ratio'] for g in grid], [g['cost_per_success'][mode] / g['cost_per_success']['cli'] for g in grid],
                          color=COLOR[mode], marker=MARKER[mode], markersize=4, linewidth=1.2)
            axis.axhline(1, color=COLOR['cli'], linewidth=1.2)
            axis.axvline(published[model], color=MUTED, linewidth=0.7, linestyle=(0, (3, 2)))
            axis.set_ylim(0.9, 5.2)
            axis.set_title(f'{MODEL_NAME[model]}, {catalog} catalog')
            if row:
                axis.set_xlabel('Cache-read price / uncached price')
            if not column:
                axis.set_ylabel('Cost per success / CLI')
    handles = [Line2D([], [], marker=MARKER[m], color=COLOR[m], markersize=4, label=MODE_NAME[m]) for m in MODES] + [Line2D([], [], color=MUTED, linewidth=0.7, linestyle=(0, (3, 2)), label='Published ratio')]
    figure.legend(handles=handles, loc='lower center', ncol=4, bbox_to_anchor=(0.5, 1.0))
    figure.tight_layout()
    save(figure, 'price-sensitivity')


def condition_map():
    tint = {'eager': '#d5e4f7', 'deferred': '#fbdfd3', 'cli': '#d1efe4'}
    letter = {'eager': 'E', 'deferred': 'D', 'cli': 'C'}
    columns = [(m, c) for m in MODELS for c in ('required', 'full')]
    table = collections.defaultdict(dict)
    for cell in SUMMARY['cells']:
        table[(cell['model'], cell['catalog'], cell['task'])][cell['mode']] = cell['cost_per_success']
    order = ['control_1', 'control_2', 'gaia_1', 'gaia_2', 'employee_demographics_report', 'employee_hierarchy_management', 'products_sales_analysis',
             'customer_segmentation_setup', 'find_salient_file', 'release_management_workflow', 'composite_1', 'composite_2']
    figure, axis = plt.subplots(figsize=(WIDTH, 3.6))
    for x, (model, catalog) in enumerate(columns):
        for y, task in enumerate(order):
            values = table[(model, catalog, task)]
            ranked = sorted(values, key=lambda m: values[m])
            margin = values[ranked[1]] / values[ranked[0]]
            axis.add_patch(plt.Rectangle((x, y), 1, 1, facecolor=tint[ranked[0]], edgecolor='white', linewidth=1.5))
            axis.text(x + 0.5, y + 0.5, f'{letter[ranked[0]]}  {margin:.2f}', ha='center', va='center', fontsize=8)
    axis.set_xlim(0, 4)
    axis.set_ylim(len(order), 0)
    axis.set_xticks([i + 0.5 for i in range(4)], [f'{MODEL_NAME[m]}\n{c}' for m, c in columns], color=INK)
    axis.set_yticks([i + 0.5 for i in range(len(order))], [TASK_LABEL[t] for t in order], color=INK)
    axis.xaxis.tick_top()
    axis.tick_params(length=0)
    axis.grid(False)
    for spine in axis.spines.values():
        spine.set_visible(False)
    figure.tight_layout()
    save(figure, 'condition-map')


def output_scatter():
    figure, axes = plt.subplots(1, 2, figsize=(WIDTH, 2.8), sharex=True, sharey=True)
    for axis, model in zip(axes, MODELS):
        for mode in MODES:
            rows = [r for r in RUNS if r['model'] == model and r['mode'] == mode]
            axis.scatter([max(int(r['tool_output_tokens_once']), 1) for r in rows], [(int(r['I']) + int(r['G'])) / 1e3 for r in rows], s=11, marker=MARKER[mode],
                         color=COLOR[mode], alpha=0.65, edgecolor='none')
        axis.set_xscale('log')
        axis.set_yscale('log')
        axis.set_xlim(left=8)
        axis.set_title(MODEL_NAME[model])
        axis.xaxis.set_major_formatter(FuncFormatter(thousands))
        axis.yaxis.set_major_formatter(FuncFormatter(thousands))
    axes[0].set_ylabel('Recorded tokens, thousands')
    figure.supxlabel('Tool-output tokens in the run, each counted once', fontsize=9)
    mode_legend(figure)
    figure.tight_layout()
    save(figure, 'tool-output')


def turns():
    rng = random.Random(2026)
    figure, axes = plt.subplots(1, 2, figsize=(WIDTH, 2.7), sharey=True)
    for axis, model in zip(axes, MODELS):
        positions = six_positions(axis)
        keys = [(c, m) for c in ('required', 'full') for m in MODES]
        for position, (catalog, mode) in zip(positions, keys):
            values = [int(r['T']) for r in RUNS if (r['model'], r['catalog'], r['mode']) == (model, catalog, mode)]
            axis.scatter([position + rng.uniform(-0.27, 0.27) for _ in values], values, s=8, marker=MARKER[mode], color=COLOR[mode], alpha=0.55, edgecolor='none')
            middle = statistics.median(values)
            axis.plot([position - 0.36, position + 0.36], [middle, middle], color=INK, linewidth=1.3)
        axis.set_yscale('log')
        axis.yaxis.set_major_formatter(FuncFormatter(thousands))
        axis.set_yticks([2, 5, 10, 20, 50, 100])
        axis.set_title(MODEL_NAME[model])
        axis.set_xlabel('Required catalog' + ' ' * 10 + 'Full catalog')
    axes[0].set_ylabel('Model requests per run')
    figure.tight_layout()
    save(figure, 'model-requests')


if __name__ == '__main__':
    for build in (resident_catalogs, eager_servers, task_tokens, components, saving_scatter, cache_cost, price_sensitivity, condition_map, output_scatter, turns):
        build()
