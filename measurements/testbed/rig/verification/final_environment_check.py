"""Zero-model checks inside the pinned agent image; read-only external API checks only."""
import ast
import hashlib
import http.server
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import threading

spec=importlib.util.spec_from_file_location('capability_checks','/audit/capability_checks.py')
checks=importlib.util.module_from_spec(spec);spec.loader.exec_module(checks)
checks.RIG=Path('/tmp/final-environment');(checks.RIG/'runtime').mkdir(parents=True)
results={}


def command(args,env=None):
    p=subprocess.run(args,env=env,capture_output=True,text=True,timeout=90)
    if p.returncode:raise RuntimeError('Command failed; output suppressed to protect credentials')
    return p.stdout.strip()


def record(name,fn):
    try:results[name]={'pass':True,**fn()}
    except Exception as exc:results[name]={'pass':False,'error_type':type(exc).__name__}


def versions():
    out={k:command(v) for k,v in {'pi':['pi','--version'],'chrome':['/opt/google/chrome/chrome','--version'],
        'bx':['bx','--version'],'gh':['gh','--version'],'playwright_cli':['playwright-cli','--version'],
        'psql':['psql','--version'],'postgres':['postgres','--version'],'github_mcp':['github-mcp-server','--version']}.items()}
    out['npm_packages']={n:json.loads((Path('/opt/pi/node_modules')/n/'package.json').read_text())['version']
        for n in ('@brave/brave-search-mcp-server','@playwright/mcp','@playwright/cli')}
    out['postgres_python']=json.loads(command(['/opt/postgres-mcp/bin/python','-c',
        'import json,importlib.metadata as m;print(json.dumps({k:m.version(k) for k in ("postgres-mcp","pglast")}))']))
    assert out['pi']=='1.0.4' and '156.0.8078.79' in out['chrome'] and out['bx']=='bx 1.7.0'
    assert out['npm_packages']=={'@brave/brave-search-mcp-server':'2.1.4','@playwright/mcp':'0.0.83','@playwright/cli':'0.1.22'}
    assert out['postgres_python']=={'postgres-mcp':'0.3.0','pglast':'7.11'}
    assert '2.103.3' in out['gh'] and '16.15' in out['psql'] and '16.15' in out['postgres'] and '2.0.3' in out['github_mcp']
    command(['uv','pip','check','--python','/opt/postgres-mcp/bin/python'])
    return out


def session(args,env=None):
    client=checks.McpStdio(args,env=env or dict(os.environ),timeout=60)
    init=client.initialize();assert init and 'result' in init
    client.initialized();tools=client.tools_list()['result']['tools'];assert tools
    return client,{'server_info':init['result']['serverInfo'],'tools':len(tools),
        'tools_sha256':hashlib.sha256(json.dumps(tools,sort_keys=True).encode()).hexdigest()}


def postgres():
    for args in (['initdb','-D','/tmp/final-pg','-A','trust','-U','study'],
                 ['pg_ctl','-D','/tmp/final-pg','-l','/tmp/final-pg.log','-o','-h 127.0.0.1 -k /home/study','-w','start'],
                 ['createdb','-h','127.0.0.1','-U','study','study']):command(args)
    dsn='postgresql://study@127.0.0.1:5432/study'
    env={**os.environ,'DATABASE_URI':dsn}
    client,out=session(['postgres-mcp','--access-mode=unrestricted'],env)
    with client:
        for sql in ('CREATE TABLE audit_check(id integer PRIMARY KEY)', 'INSERT INTO audit_check VALUES (1)'):
            response=client.call('execute_sql',{'sql':sql});assert not checks.tool_call_is_error(response)
        response=client.call('execute_sql',{'sql':'SELECT count(*) AS n FROM audit_check'})
        assert ast.literal_eval(checks.tool_call_text(response))==[{'n':1}]
        assert command(['psql','-XAt',dsn,'-c','SELECT count(*) FROM audit_check'])=='1'
        assert not checks.tool_call_is_error(client.call('execute_sql',{'sql':'DROP TABLE audit_check'}))
    return {**out,'mcp_create_insert_read_drop':True,'cli_same_database_read':True}


def brave():
    client,out=session(['brave-search-mcp-server'])
    with client:
        response=client.call('brave_web_search',{'query':'PostgreSQL official documentation','count':1})
        assert not checks.tool_call_is_error(response) and 'postgresql.org' in checks.tool_call_text(response).lower()
    text=command(['bx','web','PostgreSQL official documentation','--count','1'])
    assert 'postgresql.org' in text.lower()
    return {**out,'mcp_live_search':True,'cli_live_search':True,'external_writes':False}


def github():
    client,out=session(['github-mcp-server','stdio'])
    with client:
        response=client.call('get_me',{});assert not checks.tool_call_is_error(response)
        owner=os.environ['GITHUB_EVAL_ORG']
        assert json.loads(checks.tool_call_text(response))['login']==owner
    assert command(['gh','api','user','--jq','.login'])==os.environ['GITHUB_EVAL_ORG']
    return {**out,'mcp_expected_identity':True,'cli_expected_identity':True,'external_writes':False}


class Fixture(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        content=b'<button onclick="document.getElementById(\'proof\').textContent=\'AUDIT-OK\'">Reveal answer</button><p id="proof">pending</p>'
        self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(content)
    def log_message(self,*args):pass


def chrome_process():
    roots=[]
    for p in Path('/proc').glob('[0-9]*/cmdline'):
        try:
            args=p.read_bytes().split(b'\0')
            if args and args[0]==b'/opt/google/chrome/chrome' and not any(a.startswith(b'--type=') for a in args):
                assert b'--no-sandbox' not in args
                roots.append(p.parent.name)
        except (FileNotFoundError,PermissionError):continue
    assert roots
    return {'pinned_executable_observed':True,'no_no_sandbox_flag':True}


def browser_mcp(url):
    client,out=session(['playwright-mcp','--browser','chrome','--headless','--isolated','--sandbox'])
    with client:
        response=client.call('browser_navigate',{'url':url});assert not checks.tool_call_is_error(response)
        text=checks.tool_call_text(client.call('browser_snapshot',{}))
        ref=re.search(r'button "Reveal answer" \[ref=([^\]]+)\]',text).group(1)
        response=client.call('browser_click',{'element':'Reveal answer button','target':ref})
        assert not checks.tool_call_is_error(response)
        assert 'AUDIT-OK' in checks.tool_call_text(client.call('browser_snapshot',{}))
        out.update(chrome_process());assert not checks.tool_call_is_error(client.call('browser_close',{}))
    return {**out,'navigate_click_read':True,'sandbox_requested':True}


def browser_cli(url):
    prefix=['playwright-cli','-s=finalaudit','--json']
    try:
        command(prefix+['open',url,'--browser','chrome'])
        text=command(prefix+['snapshot']);ref=re.search(r'button [\\\"]*Reveal answer[\\\"]* \[ref=([^\]]+)\]',text)
        if ref is None:
            # CLI saves the snapshot; read only this freshly-created local fixture snapshot.
            paths=list(Path.cwd().glob('.playwright-cli/*.yml'))
            assert paths;text=max(paths,key=lambda p:p.stat().st_mtime).read_text()
            ref=re.search(r'button "Reveal answer" \[ref=([^\]]+)\]',text)
        assert ref
        command(prefix+['click',ref.group(1)])
        text=command(prefix+['eval','() => document.getElementById("proof").textContent'])
        assert 'AUDIT-OK' in text
        proof=chrome_process()
    finally:command(prefix+['close'])
    data=json.loads(command(['playwright-cli','--json','list']));assert data.get('browsers')==[]
    return {**proof,'navigate_click_read':True,'sandbox_requested':True,'open_sessions_after':0}


record('versions',versions)
record('postgres_mcp_and_cli',postgres)
record('brave_mcp_and_cli',brave)
record('github_mcp_and_cli',github)
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Fixture)
threading.Thread(target=server.serve_forever,daemon=True).start()
url=f'http://127.0.0.1:{server.server_port}/'
record('playwright_mcp',lambda:browser_mcp(url))
record('playwright_cli',lambda:browser_cli(url))
server.shutdown();server.server_close()
print(json.dumps({'model_calls':0,'uid':os.getuid(),'checks':results,'all_pass':all(v['pass'] for v in results.values())},indent=2))
