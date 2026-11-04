"""Export allowlisted engineering diagnostics; never copy prompts or credentials."""
import argparse
import fcntl
from collections import Counter
from datetime import datetime, timezone
import json
import re
from pathlib import Path

from harbor_pi.pilot import RIG, result_summary

FIELDS = ('task', 'model', 'mode', 'catalog', 'rep', 'limits', 'outcome', 'stopping_reason',
          'status', 'verifier_pass', 'clean_pass',
          'route_status', 'exposure_status', 'initial_tool_count', 'initial_tool_names',
          'initial_skill_names', 'expected_skill_names', 'skill_read_before_cli',
          'skill_metadata_matches', 'personal_context_absent', 'native_schema_sha256',
          'observed_api_settings', 'assistant_tokens', 'total_tokens', 'first_input_tokens',
          'session_ledger_present', 'compaction_entries', 'assistant_compaction_events',
          'github_cross_repository_review_flags', 'remote_cleanup_status', 'remote_bundle_sha256')


def export(root):
    root = root.resolve()
    rows = []
    for directory in sorted(root.iterdir()):
        if not directory.is_dir() or not (directory / 'scope.json').is_file():
            continue
        source = result_summary(directory)
        row = {k: source[k] for k in FIELDS if k in source}
        trials = list((directory / 'jobs').glob('*/task*/agent'))
        if trials:
            agent = trials[0]
            events = agent / 'events.jsonl'
            records = [json.loads(s) for s in events.read_text().split('\n') if s.strip()] if events.exists() else []
            messages = [e.get('message', {}) for e in records if e.get('type') == 'message_end']
            row['assistant_turns'] = sum(m.get('role') == 'assistant' for m in messages)
            frames = [json.loads(p.read_text()) for p in sorted((agent / 'raw-requests').glob('*.json'))]
            row['observed_request_frames'] = len(frames)
            row['all_observed_requests_max'] = bool(frames) and all(p.get('reasoning', {}).get('effort', p.get('reasoning_effort')) == 'max' for p in frames)
            row['largest_exposed_tool_count'] = max((len(p.get('tools', [])) for p in frames), default=0)
            if row.get('mode') == 'deferred':
                row['deferred_schemas_added_after_first_frame'] = row['largest_exposed_tool_count'] > row.get('initial_tool_count', 0)
            calls = [b for m in messages if m.get('role') == 'assistant' for b in m.get('content', []) if isinstance(b, dict) and b.get('type') == 'toolCall']
            row['native_tool_call_counts'] = dict(Counter(c['name'] for c in calls))
            row['shell_help_review_calls'] = sum(bool(re.search(r'--help|\b(?:gh(?:-github)?|bx|playwright-cli|git)\s+(?:\w+\s+)?help\b', c.get('arguments', {}).get('command', ''))) for c in calls if c['name'] == 'bash')
            row['native_bash_network_review'] = any(c['name'] == 'bash' and re.search(r'\b(?:curl|wget|urllib|requests|socket|http\.client)\b', c.get('arguments', {}).get('command', '')) for c in calls)
            row['tool_search_calls'] = sum(c['name'] == 'tool_search' for c in calls)
            row['skill_read_tool_calls'] = sum(c['name'] == 'read' and '/skills/' in c.get('arguments', {}).get('path', '') for c in calls)
            row['cli_process_counts'] = dict(Counter(t.get('program') for t in source.get('cli_invocations', [])))
            refresh = agent / 'auth-refresh-status.json'
            row['auth_refresh_status'] = json.loads(refresh.read_text()).get('status') if refresh.exists() else None
            process = agent / 'process.json'
            if process.exists():
                p = json.loads(process.read_text())
                row['process_status'] = p.get('status')
                row['stopping_reason'] = p.get('killed_reason')
            ledger = agent / 'session-usage.json'
            if ledger.exists():
                usage = json.loads(ledger.read_text())
                row['usage_totals'] = {k: usage[k] for k in ('input_tokens', 'output_tokens', 'cache_read_tokens', 'total_tokens')}
                row['usage_totals']['cache_write_tokens'] = sum(int(r['usage'].get('cacheWrite', 0)) for r in usage.get('records', []))
                row['usage_totals']['auxiliary_tokens'] = sum(sum(int(r['usage'].get(k, 0)) for k in ('input', 'output', 'cacheRead', 'cacheWrite')) for r in usage.get('records', []) if r['category'] != 'assistant')
                row['ledger_has_no_missing_usage'] = usage.get('ledger_has_no_missing_usage', False)
        rows.append(row)
    plan = json.loads((root / 'plan.json').read_text())
    return {'engineering_only': True, 'exported_utc': datetime.now(timezone.utc).isoformat(),
            'phase': root.name, 'image_id': plan['image_id'], 'manifest_digest': plan['manifest_digest'],
            'runtime_source_hashes': plan.get('runtime_source_hashes'),
            'cell_limits': plan.get('cell_limits'),
            'aggregate_recorded_token_cap': plan.get('aggregate_recorded_token_cap'),
            'max_trials': plan.get('max_trials'), 'watchdog_scope': plan.get('watchdog_scope'),
            'supervised_batch_size': plan.get('supervised_batch_size'),
            'planned_cells': len(plan['specs']), 'attempted_cells': len(rows),
            'unattempted_cells': len(plan['specs']) - len(rows),
            'verifier_passes': sum(r.get('verifier_pass', False) for r in rows),
            'clean_passes': sum(r.get('clean_pass', False) for r in rows),
            'recorded_tokens': sum(r.get('total_tokens', 0) for r in rows),
            'actual_billed_cost': None, 'route_audit_is_execution_firewall': False,
            'full_workload_or_protocol_ready': False, 'rows': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Refusing to overwrite evidence; choose a new export path')
    with (RIG / 'runtime/harbor-pilot-controller.lock').open('a') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Export only after the pilot controller stops')
        args.output.write_text(json.dumps(export(args.root), indent=2) + '\n')
    print(args.output)


if __name__ == '__main__':
    main()
