"""Accounting-only RPC canary: one control prompt, manual compact, native stats.

This is not a JSON-mode pilot cell and never changes that matrix's settings.
"""
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

argv = json.loads(Path('/home/study/rpc-argv.json').read_text())
instruction = Path('/home/study/rpc-instruction.txt').read_text()
with open('/logs/agent/stderr.txt', 'wb') as err:
    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err)
    records = queue.Queue()
    def read():
        for raw in process.stdout:
            records.put(raw)
        records.put(None)
    threading.Thread(target=read, daemon=True).start()
    deadline = time.monotonic() + 540
    def send(kind, **fields):
        process.stdin.write(json.dumps({'id': kind, 'type': kind, **fields}).encode() + b'\n')
        process.stdin.flush()
    def until(predicate):
        while True:
            raw = records.get(timeout=max(0.01, deadline - time.monotonic()))
            if raw is None:
                raise RuntimeError('RPC exited early')
            with open('/logs/agent/rpc-events.jsonl', 'ab') as log:
                log.write(raw)
            value = json.loads(raw)
            if (value.get('type') == 'message_end'
                    and value.get('message', {}).get('stopReason') == 'error'):
                process.terminate()
                raise RuntimeError('Provider error during accounting canary; trace retained; no retry')
            if value.get('type') == 'response' and value.get('success') is False:
                raise RuntimeError('RPC command failed; private trace retained')
            if predicate(value):
                return value
    try:
        send('get_state')
        state = until(lambda x: x.get('id') == 'get_state' and x.get('type') == 'response')
        assert state['data']['thinkingLevel'] == 'max'
        send('prompt', message=instruction)
        until(lambda x: x.get('type') == 'agent_settled')
        send('compact', customInstructions='Summarize the completed control task faithfully.')
        compact = until(lambda x: x.get('id') == 'compact' and x.get('type') == 'response')
        assert compact['data']['usage']['totalTokens'] > 0
        send('get_session_stats')
        stats = until(lambda x: x.get('id') == 'get_session_stats' and x.get('type') == 'response')
        Path('/logs/agent/compaction-probe.json').write_text(json.dumps({
            'main_thinking': state['data']['thinkingLevel'],
            'compaction_usage': compact['data']['usage'],
            'native_session_tokens': stats['data']['tokens'],
            'settings_exception': 'RPC, manual compaction; auto compaction disabled and keepRecentTokens=0',
            'not_a_matrix_cell': True, 'actual_billed_cost': None,
        }, indent=2) + '\n')
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
