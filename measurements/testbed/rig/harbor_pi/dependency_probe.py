"""Zero-model SQL/parser regression in an otherwise disposable container."""
import ast
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, '/tmp/probe')
import capability_checks as checks
from pglast import parse_sql

checks.RIG = Path('/tmp/probe')
(checks.RIG / 'runtime').mkdir(exist_ok=True)
env = {**os.environ, 'DATABASE_URI': 'postgresql://study@127.0.0.1:5432/study'}
for cmd in (['initdb', '-D', '/home/study/parser-probe-db', '-A', 'trust', '-U', 'study'],
            ['pg_ctl', '-D', '/home/study/parser-probe-db', '-l', '/tmp/probe/postgres.log', '-o', '-h 127.0.0.1 -k /home/study', '-w', 'start'],
            ['createdb', '-h', '127.0.0.1', '-U', 'study', 'study']):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
statements = [
    'SELECT 1 AS one',
    'CREATE TABLE probe(id integer PRIMARY KEY, label text)',
    "INSERT INTO probe VALUES (1,'alpha'),(2,'beta')",
    'WITH selected AS (SELECT * FROM probe WHERE id>0) SELECT count(*) AS n FROM selected',
    'SELECT label, count(*) FROM probe GROUP BY label HAVING count(*) > 0 ORDER BY label',
    'SELECT id, row_number() OVER (ORDER BY id) AS rank FROM probe',
    'UPDATE probe SET label=upper(label) WHERE id=1 RETURNING id',
    'DELETE FROM probe WHERE id=2 RETURNING id',
    'EXPLAIN SELECT * FROM probe',
    'DROP TABLE probe',
]
assert all(parse_sql(s) for s in statements)
malformed_rejected = False
try:
    parse_sql('SELECT FROM WHERE')
except Exception:
    malformed_rejected = True
assert malformed_rejected
with checks.McpStdio(['/opt/postgres-mcp/bin/postgres-mcp', '--access-mode=unrestricted'], env=env) as client:
    init = client.initialize()
    client.initialized()
    tools = client.tools_list()['result']['tools']
    for sql in statements[:4]:
        response = client.call('execute_sql', {'sql': sql})
        assert not checks.tool_call_is_error(response), 'SQL operation returned MCP error'
    assert ast.literal_eval(checks.tool_call_text(response)) == [{'n': 2}]
    response = client.call('execute_sql', {'sql': 'SELECT id,label FROM probe ORDER BY id'})
    assert ast.literal_eval(checks.tool_call_text(response)) == [{'id': 1, 'label': 'alpha'}, {'id': 2, 'label': 'beta'}]
    for sql in statements[4:]:
        response = client.call('execute_sql', {'sql': sql})
        assert not checks.tool_call_is_error(response), 'SQL operation returned MCP error'
print(json.dumps({
    'model_calls': 0, 'postgres_mcp_version': importlib.metadata.version('postgres-mcp'),
    'pglast_version': importlib.metadata.version('pglast'),
    'server_info': init['result']['serverInfo'], 'tool_count': len(tools),
    'tools_sha256': hashlib.sha256(json.dumps(tools, sort_keys=True).encode()).hexdigest(),
    'parser_valid_cases': len(statements), 'parser_malformed_rejected': malformed_rejected,
    'mcp_read_write_ddl_cte_group_window_explain': True,
    'coverage': 'selected unrestricted mode; not a complete restricted-mode/security proof',
    'ok': True,
}, indent=2))
