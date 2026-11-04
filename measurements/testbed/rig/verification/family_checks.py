#!/usr/bin/env python3
"""Four-family MCP/CLI connection checks [ours].

Bounded, evidence-producing checks of the real capability families on this
machine. Read-only or disposable only; never mutates user repositories,
never installs global dependencies, never prints credential values.

Families:
  brave      npx @brave/brave-search-mcp-server (key sourced from the
             existing bx config, passed via env only) + one `bx search`
  browser    npx @playwright/mcp handshake + tools/list (+ optional
             chromium launch via pi's own catalog probe)
  github     gh CLI auth status + read-only view of the task repo;
             github-mcp-server binary presence
  database   psql client/server reachability; DSN availability; uvx presence

Writes sanitized JSON evidence to --evidence-dir/families.json plus logs.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CANARY = HERE / "canary"


def run(argv, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True,
                          timeout=kw.pop("timeout", 120), **kw)


def mcp_handshake(cmd: list[str], env: dict | None = None,
                  call_tool: tuple[str, dict] | None = None,
                  timeout: int = 120, hold_stdin: bool = False) -> dict:
    """Spawn a stdio MCP server; initialize + tools/list (+ optional call)."""
    if hold_stdin:
        return _mcp_handshake_interactive(cmd, env, call_tool, timeout)
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "rig-verification", "version": "1.0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    rid = 3
    if call_tool:
        name, args = call_tool
        lines.append({"jsonrpc": "2.0", "id": rid, "method": "tools/call",
                      "params": {"name": name, "arguments": args}})
        rid += 1
    inp = "\n".join(json.dumps(l) for l in lines) + "\n"
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, input=inp, capture_output=True, text=True,
                              timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout after {timeout}s"}
    dt = round(time.time() - t0, 1)
    responses = []
    for line in proc.stdout.split('\n'):
        line = line.strip()
        if not line:
            continue
        try:
            responses.append(json.loads(line))
        except json.JSONDecodeError:
            responses.append({"unparsed": line[:200]})
    by_id = {r.get("id"): r for r in responses if isinstance(r, dict)}
    init = by_id.get(1, {})
    tools = by_id.get(2, {}).get("result", {}).get("tools", [])
    out = {
        "ok": init.get("result", {}).get("serverInfo") is not None,
        "server_info": init.get("result", {}).get("serverInfo"),
        "n_tools": len(tools),
        "tool_names": [t.get("name") for t in tools][:40],
        "duration_s": dt,
        "stderr_head": proc.stderr[:400],
    }
    if call_tool:
        cres = by_id.get(3, {})
        content = cres.get("result", {}).get("content", [])
        text = content[0].get("text", "") if content else ""
        out["tool_call_ok"] = cres.get("result", {}).get("isError") is False
        out["tool_call_text_head"] = text[:300]
    return out


def _mcp_handshake_interactive(cmd, env, call_tool, timeout) -> dict:
    """Same protocol but stdin stays open until responses settle — needed
    for servers whose first tool call launches a browser (playwright)."""
    import threading
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, env=env)
    responses: list[dict] = []

    def reader():
        for line in proc.stdout:
            try:
                responses.append(json.loads(line))
            except json.JSONDecodeError:
                responses.append({"unparsed": line[:200]})

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    t0 = time.time()

    def send(obj):
        proc.stdin.write(json.dumps(obj) + "\n")
        proc.stdin.flush()

    def wait_id(rid, deadline):
        while time.time() < deadline:
            if any(r.get("id") == rid for r in responses):
                return True
            time.sleep(0.2)
        return False

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "rig-verification", "version": "1.0"}}})
    if not wait_id(1, t0 + timeout):
        proc.kill()
        return {"ok": False, "error": "initialize timeout"}
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    if not wait_id(2, t0 + timeout):
        proc.kill()
        return {"ok": False, "error": "tools/list timeout"}
    out = {"ok": True}
    out["server_info"] = next((r["result"].get("serverInfo")
                               for r in responses if r.get("id") == 1), None)
    tools = next((r["result"].get("tools", []) for r in responses
                  if r.get("id") == 2), [])
    out["n_tools"] = len(tools)
    out["tool_names"] = [t.get("name") for t in tools][:40]
    if call_tool:
        name, args = call_tool
        send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
              "params": {"name": name, "arguments": args}})
        got = wait_id(3, t0 + timeout)
        cres = next((r for r in responses if r.get("id") == 3), {})
        content = cres.get("result", {}).get("content", [])
        text = content[0].get("text", "") if content else ""
        out["tool_call_ok"] = bool(got) and \
            cres.get("result", {}).get("isError") is False
        out["tool_call_text_head"] = text[:300]
    out["duration_s"] = round(time.time() - t0, 1)
    proc.kill()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-dir", type=Path, default=HERE / "evidence")
    ap.add_argument("--skip-browser-launch", action="store_true")
    args = ap.parse_args()
    ev = args.evidence_dir
    ev.mkdir(parents=True, exist_ok=True)
    results: dict = {"generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                    time.gmtime())}

    # ---- brave ----
    brave: dict = {}
    bx = shutil.which("bx")
    brave["bx_on_path"] = bool(bx)
    if bx:
        p = run([bx, "--version"])
        brave["bx_version"] = p.stdout.strip().splitlines()[-1][:40]
        cfg = Path.home() / ".config" / "brave-search" / "config.json"
        brave["bx_config_present"] = cfg.is_file()
        if cfg.is_file():
            key = json.loads(cfg.read_text()).get("api_key")
            brave["bx_config_has_api_key"] = bool(key)
            if key:
                pkg_ok = run(["npm", "view", "@brave/brave-search-mcp-server",
                              "version"], timeout=60)
                brave["npm_latest_version"] = pkg_ok.stdout.strip() or None
                env = dict(os.environ, BRAVE_API_KEY=key)
                hs = mcp_handshake(
                    ["npx", "-y", "@brave/brave-search-mcp-server"],
                    env=env,
                    call_tool=("brave_web_search",
                               {"query": "pi coding agent earendil",
                                "count": 1}),
                    timeout=180)
                # sanitize: never echo env or key
                hs.pop("stderr_head", None)
                brave["mcp_server"] = hs
                q = run([bx, "web", "earendil pi coding agent", "--count",
                         "1"], timeout=60)
                brave["bx_search_exit"] = q.returncode
                brave["bx_search_head"] = q.stdout[:300] if \
                    q.returncode == 0 else q.stderr[:300]
    results["brave"] = brave

    # ---- browser ----
    browser: dict = {}
    cache = Path.home() / ".cache" / "ms-playwright"
    browser["chromium_cache_present"] = cache.is_dir()
    if cache.is_dir():
        browser["chromium_versions"] = sorted(
            p.name for p in cache.iterdir())[:10]
    hs = mcp_handshake(["npx", "-y", "@playwright/mcp"], timeout=120,
                       call_tool=("browser_navigate",
                                  {"url": "about:blank"}),
                       hold_stdin=True)
    hs.pop("stderr_head", None)
    browser["mcp_server"] = hs
    results["browser"] = browser

    # ---- github ----
    gh: dict = {}
    gh["gh_on_path"] = bool(shutil.which("gh"))
    gh["github_mcp_server_on_path"] = bool(
        shutil.which("github-mcp-server"))
    p = run(["gh", "auth", "status"], timeout=30)
    gh["gh_auth_exit"] = p.returncode
    gh["gh_logged_in"] = "Logged in to github.com" in (p.stdout + p.stderr)
    scopes = [ln for ln in (p.stdout + p.stderr).splitlines()
              if "Token scopes" in ln]
    gh["gh_token_scopes_line"] = scopes[0].strip()[:120] if scopes else None
    repository = os.environ.get('TESTBED_GH_REPO')
    if repository:
        v = run(["gh", "repo", "view", repository, "--json",
                 "name,visibility,pushedAt"], timeout=30)
        gh["task_repo_readable"] = v.returncode == 0
        if v.returncode == 0:
            try:
                gh["task_repo"] = json.loads(v.stdout)
            except json.JSONDecodeError:
                pass
    else:
        gh["task_repo_readable"] = None
    results["github"] = gh

    # ---- database ----
    db: dict = {}
    db["psql_on_path"] = bool(shutil.which("psql"))
    if db["psql_on_path"]:
        db["psql_version"] = run(["psql", "--version"]).stdout.strip()[:60]
    db["pg_isready_on_path"] = bool(shutil.which("pg_isready"))
    if db["pg_isready_on_path"]:
        r = run(["pg_isready", "-h", "127.0.0.1", "-p", "5432"], timeout=15)
        db["local_server_reply"] = r.stdout.strip()[:80]
    db["testbed_pg_dsn_env_present"] = "TESTBED_PG_DSN" in os.environ
    db["uvx_on_path"] = bool(shutil.which("uvx"))
    db["initdb_on_path"] = bool(shutil.which("initdb"))
    results["database"] = db

    # ---- pass/fail summary against campaign skeleton needs ----
    results["summary"] = {
        "brave": brave.get("mcp_server", {}).get("ok") is True
        and brave.get("bx_search_exit") == 0,
        "browser_mcp_handshake": browser.get("mcp_server", {}).get("ok")
        is True,
        "github_mcp_route": gh.get("github_mcp_server_on_path") is True,
        "github_cli_route": gh.get("task_repo_harmony_readable") is True,
        "database_any_route": (db.get("testbed_pg_dsn_env_present") is True
                               and db.get("psql_on_path") is True),
    }
    (ev / "families.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results["summary"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
