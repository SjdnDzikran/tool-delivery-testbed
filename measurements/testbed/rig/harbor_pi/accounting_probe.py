"""Harbor custom agent for the separate, bounded native-compaction canary."""
import json
import os
from pathlib import Path
import shlex
import tempfile

import runner
from harbor_pi.adapter import PiAgent, AGENT, WORK, LOGS, PI
from harbor_pi.pilot_support import persist_auth, session_usage
from harbor_pi.route_contract import instruction_for


class AccountingProbeAgent(PiAgent):
    def __init__(self, *args, http_observer=False, **kwargs):
        self.http_observer = http_observer
        super().__init__(*args, **kwargs)

    @staticmethod
    def name():
        return 'pi-accounting-canary'

    async def run(self, instruction, environment, context):
        m = json.loads(json.dumps(self.manifest))
        m['harness']['binary'] = PI
        argv = runner.build_argv(m, self.spec, '', Path(AGENT), Path(LOGS) / 'sessions')[:-2]
        argv[argv.index('json')] = 'rpc'
        argv += ['-e', '/opt/study/observer.ts']
        if self.http_observer:
            argv += ['-e', '/opt/study/http-observer.mjs']
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'argv.json').write_text(json.dumps(argv))
            (root / 'instruction.txt').write_text(instruction_for(m, instruction))
            model = m['models'][self.spec['model']]
            (root / 'settings.json').write_text(json.dumps({
                'defaultProvider': model['provider'], 'defaultModel': model['id'],
                'defaultThinkingLevel': 'max',
                'compaction': {'enabled': False, 'keepRecentTokens': 0, 'reserveTokens': 16384},
            }))
            for name, target in (('argv.json', '/home/study/rpc-argv.json'),
                                 ('instruction.txt', '/home/study/rpc-instruction.txt'),
                                 ('settings.json', AGENT + '/settings.json')):
                await environment.upload_file(root / name, target)
            await environment.upload_file(Path(__file__).with_name('compaction_probe.py'), '/home/study/compaction_probe.py')
            permissions = await environment.exec(f'chown study:study {AGENT}/settings.json && chmod 600 {AGENT}/settings.json', user='root')
            if permissions.return_code:
                raise RuntimeError('Cannot set canary configuration permissions')
        if self.http_observer:
            await environment.upload_file(Path(__file__).with_name('http_observer.mjs'), '/opt/study/http-observer.mjs')
            await self._exec(environment, 'mkdir -p -m 700 /logs/agent/http-requests')
        observe = ('PI_HTTP_OBSERVER_DIR=/logs/agent/http-requests '
                   if self.http_observer else '')
        inner = '. /home/study/.trial-env; exec python3 /home/study/compaction_probe.py'
        command = (f'env -i HOME=/home/study USER=study LOGNAME=study LANG=C.UTF-8 '
                   f'PATH=/usr/local/bin:/usr/bin:/bin PI_CODING_AGENT_DIR={AGENT} '
                   f'PI_SKIP_VERSION_CHECK=1 PI_OFFLINE=1 {observe}/bin/sh -c ' + shlex.quote(inner))
        try:
            result = await environment.exec(command, user='study', cwd=WORK)
        finally:
            state = await persist_auth(self, environment)
            (self.logs_dir / 'auth-refresh-status.json').write_text(json.dumps({'status': state}) + '\n')
        (self.logs_dir / 'rpc-driver-stderr.txt').write_text(result.stderr or '')
        (self.logs_dir / 'rpc-driver-stdout.txt').write_text(result.stdout or '')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            await environment.download_dir(LOGS + '/sessions', root / 'sessions')
            ledger = session_usage(root / 'sessions')
            (self.logs_dir / 'session-usage.json').write_text(json.dumps(ledger, indent=2) + '\n')
            if result.return_code:
                raise RuntimeError('Accounting RPC canary failed; native trace and usage retained; no replay')
            await environment.download_file(LOGS + '/compaction-probe.json', root / 'proof.json')
            proof = json.loads((root / 'proof.json').read_text())
        http_proof = None
        if self.http_observer:
            from collections import Counter
            import hashlib
            def digest(value):
                return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                await environment.download_dir(LOGS + '/http-requests', root / 'http')
                await environment.download_dir(LOGS + '/raw-requests', root / 'hook')
                observed = [json.loads(p.read_text()) for p in (root / 'http').glob('*.json')]
                main = [json.loads(p.read_text()) for p in (root / 'hook').glob('*.json')]
            unmatched = Counter(digest(p) for p in main) - Counter(digest(r['payload']) for r in observed)
            assert not unmatched, 'HTTP capture differs from native main-request payloads'
            assert len(observed) == len(main) + 1, 'Expected one separately observed compaction request'
            assert all(r.get('http_status') == 200 for r in observed)
            main_hashes = set(digest(p) for p in main)
            aux = [r for r in observed if digest(r['payload']) not in main_hashes]
            http_proof = {'http_requests': len(observed), 'main_hook_requests': len(main),
                          'main_payloads_unchanged': True, 'compaction_http_requests': len(aux),
                          'auxiliary_api_settings': [{k: r['payload'][k] for k in ('model', 'reasoning', 'reasoning_effort', 'thinking', 'max_tokens', 'max_output_tokens') if k in r['payload']} for r in aux],
                          'endpoints': sorted({r['endpoint'] for r in observed})}
        assert ledger['total_tokens'] == proof['native_session_tokens']['total']
        assert 'compaction' in {r['category'] for r in ledger['records']}
        (self.logs_dir / 'accounting-proof.json').write_text(json.dumps({
            'session_ledger_matches_native_stats': True, 'proof': proof, 'http_capture': http_proof,
            'assistant_tokens': sum(r['usage'].get('totalTokens', 0) for r in ledger['records'] if r['category'] == 'assistant'),
            'all_recorded_tokens': ledger['total_tokens'], 'complete_run_accounting': False,
        }, indent=2) + '\n')
        context.n_input_tokens = ledger['input_tokens']
        context.n_output_tokens = ledger['output_tokens']
        context.n_cache_tokens = ledger['cache_read_tokens']


def main():
    import argparse
    import fcntl
    import hashlib
    import subprocess
    import sys
    from harbor_pi.adapter import checked_spec
    from harbor_pi.bridge import docker_env
    from harbor_pi.pilot import MANIFEST, RIG, prepare_task
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=MANIFEST)
    parser.add_argument('--model', choices=('gpt6luna', 'glm53flash'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--http-observer', action='store_true')
    args = parser.parse_args()
    if not args.execute:
        parser.error('--execute required: this separately bounded canary spends tokens')
    print('Waiting for exclusive pilot lock; no concurrent model invocations', flush=True)
    with (RIG / 'runtime/harbor-pilot-controller.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        m = runner.load_manifest(args.manifest)
        actual = subprocess.check_output(['docker', 'image', 'inspect', m['harness']['harbor_pilot_image'], '--format', '{{.Id}}'], env=docker_env(), text=True).strip()
        if actual != m['harness']['harbor_image_id']:
            raise ValueError('Accounting canary image differs from its frozen pin')
        job = prepare_task(args.manifest, args.output.resolve(), checked_spec(m, 'control_1', 'eager', args.model))
        config = json.loads(job.read_text())
        config['agents'][0]['import_path'] = 'harbor_pi.accounting_probe:AccountingProbeAgent'
        config['agents'][0]['kwargs']['http_observer'] = args.http_observer
        runner.atomic_write_json(job, config)
        scopefile = job.parent / 'scope.json'
        scope = json.loads(scopefile.read_text())
        scope['accounting_canary_not_matrix_cell'] = True
        names = ['accounting_probe.py', 'compaction_probe.py', 'pilot_support.py', 'adapter.py']
        if args.http_observer:
            names.append('http_observer.mjs')
        scope['passive_http_observer'] = args.http_observer
        frozen = job.parent / 'frozen-source'
        frozen.mkdir()
        for name in names:
            (frozen / name).write_bytes(Path(__file__).with_name(name).read_bytes())
        scope['canary_source_hashes'] = {n: hashlib.sha256((frozen / n).read_bytes()).hexdigest() for n in names}
        runner.atomic_write_json(scopefile, scope)
        status = subprocess.call([sys.executable, '-m', 'harbor_pi.bridge', 'run', str(job), '--execute'], env={**os.environ, 'PYTHONPATH': str(RIG)})
        if any(hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() != h
               for n, h in scope['canary_source_hashes'].items()):
            raise RuntimeError('Canary source changed during execution; preserve attempt as contaminated')
        return status


if __name__ == '__main__':
    raise SystemExit(main())
