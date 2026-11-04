"""Separate verifier entry point for the first real-task admission phase."""
import asyncio
import importlib.util
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import threading
import time
from urllib.request import Request,urlopen

WORK = Path('/home/study/workspace')
PG = '/usr/lib/postgresql/16/bin/'


def github_verify():
    target=json.loads(Path('/tests/repository.json').read_text())
    owner,name=target['repository'].split('/')
    spec=importlib.util.spec_from_file_location('upstream_verifier','/tests/upstream_verify.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original_api=module._get_github_api
    original_get=module.requests.get
    statuses=[]
    errors=[]
    def get(url,*args,**kwargs):
        kwargs.setdefault('timeout',45)
        try:
            response=original_get(url,*args,**kwargs)
        except Exception as exc:
            errors.append(type(exc).__name__)
            raise
        statuses.append(response.status_code)
        return response
    def scoped_api(endpoint,headers,org,repo=target['base_repository']):
        if org!=owner or repo!=target['base_repository']:
            raise ValueError('Unexpected upstream verifier repository route')
        return original_api(endpoint,headers,owner,name)
    # Only the deployment target changes. The original verifier file, checks,
    # filenames, branch requirements and live PR/squash grading remain intact.
    module._get_github_api=scoped_api
    module.requests.get=get
    verdict=module.verify()
    Path('/logs/verifier/github-transport.json').write_text(json.dumps({
        'original_verifier_verdict':verdict,'status_codes':statuses,'transport_errors':errors,
        'repository_alias_only':True})+'\n')
    if errors or any(s in (401,403,429) or s>=500 for s in statuses):
        return 4
    return 0 if verdict else 1


def state_server(marker=None):
    # Harbor 0.23 rematerializes sidecar artifacts in main, not the sidecar.
    # Expose only these two snapshots, never /tests, labels or a directory listing.
    allowed={'/shopping-state.sql':Path('/tmp/shopping-state.sql'),
             '/shopping-state.sha256':Path('/tmp/shopping-state.sha256')}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            size=int(self.headers.get('Content-Length','0'))
            if self.path!='/restore-ready' or size!=64 or self.rfile.read(size).decode()!=marker:
                self.send_error(400);return
            self.server.restore_ready.set()
            self.send_response(200);self.send_header('Content-Length','0');self.end_headers()
        def do_GET(self):
            path=allowed.get(self.path)
            if path is None or not path.is_file():self.send_error(404);return
            self.send_response(200);self.send_header('Content-Length',str(path.stat().st_size));self.end_headers()
            with path.open('rb') as source:shutil.copyfileobj(source,self.wfile)
    server=ThreadingHTTPServer(('0.0.0.0',8765),Handler)
    server.restore_ready=threading.Event()
    threading.Thread(target=server.serve_forever,daemon=True).start()
    return server


def browser_verify():
    marker=json.loads(Path('/tests/site.json').read_text())['marker']
    server=state_server(marker)
    try:return browser_verify_ready(server)
    finally:server.shutdown();server.server_close()


def browser_verify_ready(server):
    if not server.restore_ready.wait(400):raise RuntimeError('Separate shopping state restore did not become ready')
    events=Path('/logs/agent/events.jsonl')
    if not events.is_file():return 3
    messages=[]
    for line in events.read_text().split('\n'):
        if not line.strip():continue
        event=json.loads(line);message=event.get('message',{})
        if event.get('type')=='message_end' and message.get('role')=='assistant':
            text='\n'.join(b.get('text','') for b in message.get('content',[]) if isinstance(b,dict) and b.get('type')=='text')
            messages.append({'role':'assistant','status':'completed','type':'message','content':[{'type':'output_text','text':text}]})
    path=Path('/logs/verifier/browser-messages.json');path.write_text(json.dumps(messages))
    from shopping_original_verify import run
    verdict=asyncio.run(run(Path('/tests/upstream_verify.py'),path))
    Path('/logs/verifier/browser-deployment.json').write_text(json.dumps({
        'candidate_adaptation':True,'separate_state_restored':True,'original_verifier_unchanged':True,
        'chrome':'156.0.8078.79','chromium_sandbox':True,'original_verdict':verdict})+'\n')
    return 0 if verdict else 1


def main():
    kind = sys.argv[1]
    if kind in ('sql','composite_1','composite_2'):
        dump = WORK / 'task-state.dump'
        if not dump.is_file() or not dump.stat().st_size:
            return 3
        subprocess.run([PG + 'initdb', '-D', '/home/study/verifier-pg', '-A', 'trust', '-U', 'study'], check=True)
        subprocess.run([PG + 'pg_ctl', '-D', '/home/study/verifier-pg', '-l', '/home/study/verifier-pg.log',
                        '-o', '-h 127.0.0.1 -k /home/study -p 5432', '-w', 'start'], check=True)
        subprocess.run([PG + 'createdb', '-h', '127.0.0.1', '-U', 'study', 'study'], check=True)
        subprocess.run([PG + 'pg_restore', '--exit-on-error', '--no-owner', '--no-acl',
                        '-h', '127.0.0.1', '-U', 'study', '-d', 'study', str(dump)], check=True)
        if kind.startswith('composite_'):
            directory={'composite_1':'composite_1_search_db','composite_2':'composite_2_db_repo'}[kind]
            command=['/opt/verifier/bin/python','/tests/testbed/composites/'+directory+'/verify.py',
                '--artifacts',str(WORK),'--psql-cmd',PG+'psql','--dsn','postgresql://study@127.0.0.1:5432/study',
                '--result','/logs/verifier/composite-result.json']
            if kind=='composite_2':command+=['--repo',os.environ['TESTBED_GH_REPO']]
            return subprocess.run(command).returncode
        env = dict(os.environ, POSTGRES_HOST='127.0.0.1', POSTGRES_PORT='5432',
                   POSTGRES_DATABASE='study', POSTGRES_USERNAME='study', POSTGRES_PASSWORD='')
        return subprocess.run(['/opt/verifier/bin/python', '/tests/upstream_verify.py'], env=env).returncode
    if kind == 'browser':
        return browser_verify()
    if kind == 'github':
        return github_verify()
    if kind == 'gaia':
        return subprocess.run(['/usr/local/bin/python3', '/tests/testbed/gaia/verify_gaia.py',
            '--artifacts', str(WORK), '--task', '/tests/testbed/gaia/task.json',
            '--transcript', '/logs/agent/events.jsonl']).returncode
    raise ValueError('Unsupported actual-task verifier')


if __name__ == '__main__':
    try:
        code = main()
    except Exception as exc:
        print('Verifier infrastructure error:', type(exc).__name__,str(exc), file=sys.stderr)
        code = 4
    raise SystemExit(code)
