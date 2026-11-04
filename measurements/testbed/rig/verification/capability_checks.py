#!/usr/bin/env python3
"""Zero-model MCP probe of the pinned local capability servers [ours].

Speaks raw JSON-RPC over stdio (no model spend, no SDK) to each pinned
server: initialize -> tools/list -> one tiny real operation. Companion to
family_checks.py; this variant exercises the pinned rig/runtime binaries
and records sanitized evidence. Credentials are passed via environment and
never printed.

Usage (from rig/, after `. env.sh`):
  BRAVE_API_KEY=... TESTBED_PG_DSN=... python3 verification/capability_checks.py \
      [--evidence-dir verification/evidence] [--fixture-url http://127.0.0.1:5580/]

GitHub MCP is probed without a PAT: the expected outcome is recorded as
auth-required (tools/list may succeed; tool calls cannot).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import queue
import threading
import tempfile
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RIG = HERE.parent
BIN = RIG / "runtime" / "bin"
BX_CONFIG = Path.home() / ".config" / "brave-search" / "config.json"

SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{8,})")


def redact(obj):
    if isinstance(obj, str):
        return SECRET_RE.sub("<redacted>", obj)[:400]
    if isinstance(obj, dict):
        return {k: redact(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


class McpStdio:
    """Minimal stdio MCP client: initialize, tools/list, tools/call."""

    def __init__(self, cmd, env=None, timeout=90):
        self._stderr = tempfile.TemporaryFile(mode="w+")
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=self._stderr, text=True, env=env,
            cwd=RIG / "runtime")
        self._lines = queue.Queue()
        def read_lines():
            for line in self.proc.stdout:
                self._lines.put(line)
            self._lines.put(None)
        threading.Thread(target=read_lines, daemon=True).start()
        self.timeout = timeout
        self._id = 0
        self.stderr_tail = ""

    def _send(self, payload):
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()

    def _recv(self, want_id):
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            try:
                line = self._lines.get(timeout=max(0.001, deadline - time.time()))
            except queue.Empty:
                raise TimeoutError(f"MCP response timed out ({self.timeout}s)") from None
            if line is None:
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == want_id:
                return msg
        return None

    def request(self, method, params=None):
        self._id += 1
        rid = self._id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method,
                    "params": params or {}})
        return self._recv(rid)

    def initialize(self):
        return self.request("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "rig-capability-checks", "version": "1.0"}})

    def initialized(self):
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def tools_list(self):
        return self.request("tools/list")

    def call(self, name, arguments):
        return self.request("tools/call", {"name": name, "arguments": arguments})

    def close(self):
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        self.proc.stdin.close()
        self.proc.stdout.close()
        self._stderr.close()
        return self.stderr_tail

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def tool_call_text(resp) -> str:
    """Concatenate text content of a tools/call result."""
    if not resp or "result" not in resp:
        return ""
    content = resp["result"].get("content", [])
    parts = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text", ""))
    return "\n".join(parts)


def tool_call_is_error(resp) -> bool:
    return bool(resp and resp.get("result", {}).get("isError"))


def parse_json_objects(text: str) -> list:
    """Parse a sequence of whitespace-separated JSON objects (the brave MCP
    2.1.4 brave_web_search result is one JSON object per result item)."""
    dec = json.JSONDecoder()
    items, i = [], 0
    while i < len(text):
        while i < len(text) and text[i] in " \n\t\r":
            i += 1
        if i >= len(text):
            break
        obj, i = dec.raw_decode(text, i)
        items.append(obj)
    return items


def check_brave(evidence, fixture_url):
    key = os.environ.get("BRAVE_API_KEY")
    if not key:
        return {"route": "brave-mcp", "ok": False,
                "status": "auth-required",
                "detail": "BRAVE_API_KEY not in host environment"}
    env = dict(os.environ)
    env["BRAVE_API_KEY"] = key
    out = {"route": "brave-mcp", "server": str(BIN / "brave-search-mcp-server")}
    with McpStdio([str(BIN / "brave-search-mcp-server")], env=env) as mcp:
        init = mcp.initialize()
        info = (init or {}).get("result", {}).get("serverInfo", {})
        out["serverInfo"] = {"name": info.get("name"), "version": info.get("version")}
        mcp.initialized()
        tools = mcp.tools_list()
        names = sorted(t.get("name", "") for t in
                       (tools or {}).get("result", {}).get("tools", []))
        out["tools"] = names
        call = mcp.call("brave_web_search",
                        {"query": "University of Gadjah Mada founding year", "count": 1})
        text = tool_call_text(call)
        try:
            items = [o for o in parse_json_objects(text) if isinstance(o, dict)]
            out["probe"] = {"ok": bool(items),
                            "top_url": redact(items[0].get("url", "")) if items else None,
                            "n_results": len(items)}
        except json.JSONDecodeError:
            out["probe"] = {"ok": False, "raw_head": redact(text[:200])}
    out["ok"] = bool(out.get("probe", {}).get("ok"))
    out["status"] = "pass" if out["ok"] else "fail"
    return out


def check_playwright_mcp(evidence, fixture_url):
    out = {"route": "browser-mcp", "server": str(BIN / "playwright-mcp")}
    with McpStdio([str(BIN / "playwright-mcp"), "--browser", "chrome",
                   "--headless", "--isolated"],
                  env=dict(os.environ)) as mcp:
        init = mcp.initialize()
        info = (init or {}).get("result", {}).get("serverInfo", {})
        out["serverInfo"] = {"name": info.get("name"), "version": info.get("version")}
        mcp.initialized()
        tools = mcp.tools_list()
        names = sorted(t.get("name", "") for t in
                       (tools or {}).get("result", {}).get("tools", []))
        out["tools_n"] = len(names)
        nav = mcp.call("browser_navigate", {"url": fixture_url})
        out["navigate_ok"] = bool(nav and "result" in nav and not tool_call_is_error(nav))
        if not out["navigate_ok"]:
            out["failure_kind"] = ("sandbox-unavailable" if "sandbox" in tool_call_text(nav).lower()
                                   else "navigation-failed")
        snap = mcp.call("browser_snapshot", {})
        snap_text = tool_call_text(snap)
        ref = None
        m = re.search(r'button "Reveal answer" \[ref=([^\]]+)\]', snap_text)
        if m:
            ref = m.group(1)
        out["button_ref_found"] = ref is not None
        if ref:
            click = mcp.call("browser_click",
                             {"element": "Reveal answer button", "target": ref})
            out["click_ok"] = not tool_call_is_error(click)
            snap2 = tool_call_text(mcp.call("browser_snapshot", {}))
            out["token_seen"] = "SMOKE-TOKEN-4F7A" in snap2
    out["ok"] = bool(out.get("navigate_ok") and out.get("button_ref_found")
                     and out.get("click_ok") and out.get("token_seen"))
    out["status"] = "pass" if out["ok"] else "fail"
    return out


def check_postgres(evidence, fixture_url):
    import ast
    dsn = os.environ.get("TESTBED_PG_DSN")
    if not dsn:
        return {"route": "postgres-mcp", "ok": False, "status": "blocked",
                "detail": "TESTBED_PG_DSN not set (run scripts/pgfixture start)"}
    env = dict(os.environ)
    env["DATABASE_URI"] = dsn
    out = {"route": "postgres-mcp", "server": str(BIN / "postgres-mcp")}
    with McpStdio([str(BIN / "postgres-mcp"), "--access-mode=unrestricted"],
                  env=env) as mcp:
        init = mcp.initialize()
        info = (init or {}).get("result", {}).get("serverInfo", {})
        out["serverInfo"] = {"name": info.get("name"), "version": info.get("version")}
        mcp.initialized()
        tools = mcp.tools_list()
        names = sorted(t.get("name", "") for t in
                       (tools or {}).get("result", {}).get("tools", []))
        out["tools"] = names
        sel_text = tool_call_text(mcp.call("execute_sql",
                                           {"sql": "SELECT 1 AS one"}))
        try:
            rows = ast.literal_eval(sel_text)
            out["read_ok"] = rows == [{"one": 1}]
        except (ValueError, SyntaxError):
            out["read_ok"] = False
        mcp.call("execute_sql", {"sql":
            "CREATE TABLE IF NOT EXISTS capability_probe(id int primary key)"})
        mcp.call("execute_sql", {"sql":
            "INSERT INTO capability_probe VALUES (1) ON CONFLICT DO NOTHING"})
        cnt_text = tool_call_text(mcp.call("execute_sql",
                                           {"sql": "SELECT count(*) AS n FROM capability_probe"}))
        try:
            out["write_ok"] = ast.literal_eval(cnt_text) == [{"n": 1}]
        except (ValueError, SyntaxError):
            out["write_ok"] = False
        mcp.call("execute_sql", {"sql": "DROP TABLE IF EXISTS capability_probe"})
    out["ok"] = bool(out.get("read_ok") and out.get("write_ok"))
    out["status"] = "pass" if out["ok"] else "fail"
    return out


def check_github(evidence, fixture_url):
    out = {"route": "github-mcp", "server": str(BIN / "github-mcp-server")}
    token = os.environ.get("STUDY_GITHUB_TOKEN")
    env = dict(os.environ)
    if token:
        env["GITHUB_PERSONAL_ACCESS_TOKEN"] = token
    with McpStdio([str(BIN / "github-mcp-server"), "stdio"], env=env,
                  timeout=60) as mcp:
        init = mcp.initialize()
        info = (init or {}).get("result", {}).get("serverInfo", {})
        out["serverInfo"] = {"name": info.get("name"), "version": info.get("version")}
        started = bool(info)
        if started:
            mcp.initialized()
            tools = mcp.tools_list()
            names = sorted(t.get("name", "") for t in
                           (tools or {}).get("result", {}).get("tools", []))
            out["tools_n"] = len(names)
            call = mcp.call("get_me", {})
            text = tool_call_text(call)
            login = None
            try:
                login = json.loads(text).get("login")
            except json.JSONDecodeError:
                pass
            if login is not None:
                out["status"] = "pass"
                out["ok"] = True
                out["detail"] = "authenticated as a GitHub login"
            elif "login/device" in text or "authorize" in text.lower():
                out["status"] = "auth-required"
                out["ok"] = False
                out["detail"] = ("server surfaced its device-code OAuth login "
                                 "(no PAT set); set STUDY_GITHUB_TOKEN for the "
                                 "runner or complete OAuth login interactively")
            else:
                out["status"] = "auth-required"
                out["ok"] = False
                out["detail"] = redact(text)[:200] or "tools/call failed"
        else:
            out["status"] = "fail"
            out["ok"] = False
            out["detail"] = "server did not initialize without a token"
    out["token_provided"] = bool(token)
    return out


def check_cli_bx(evidence, fixture_url):
    proc = subprocess.run(["bx", "web",
                           "University of Gadjah Mada founding year",
                           "--count", "1"],
                          capture_output=True, text=True, timeout=60,
                          env=dict(os.environ))
    out = {"route": "brave-cli", "ok": proc.returncode == 0}
    if out["ok"]:
        try:
            web = json.loads(proc.stdout).get("web", {}).get("results", [])
            out["probe"] = {"n_results": len(web),
                            "top_url": redact(web[0].get("url", "")) if web else None}
            out["ok"] = bool(web)
        except json.JSONDecodeError:
            out["ok"] = False
            out["error"] = "unparseable output"
    else:
        out["error"] = redact(proc.stderr[:200])
    out["status"] = "pass" if out["ok"] else "fail"
    return out


def check_cli_playwright(evidence, fixture_url):
    """Drive the pinned playwright-cli through open -> click -> read."""
    env = dict(os.environ)
    workdir = Path(evidence) / ".pwcli-probe"
    workdir.mkdir(parents=True, exist_ok=True)
    steps = {}
    try:
        for name, argv in [
            ("open", ["playwright-cli", "open", "--browser", "chrome", fixture_url]),
            ("snapshot", ["playwright-cli", "snapshot"]),
        ]:
            proc = subprocess.run(argv, capture_output=True, text=True,
                                  timeout=90, env=env, cwd=workdir)
            steps[name] = {"rc": proc.returncode}
            if proc.returncode:
                steps[name]["failure_kind"] = ("sandbox-unavailable" if "sandbox" in proc.stderr.lower()
                                                else "command-failed")
            if name == "snapshot" and proc.returncode == 0:
                ymls = sorted((workdir / ".playwright-cli").glob("page-*.yml"))
                if ymls:
                    content = ymls[-1].read_text(errors="replace")
                    import re as _re
                    m = _re.search(r'button "Reveal answer" \[ref=([^\]]+)\]', content)
                    steps["snapshot"]["ref_found"] = bool(m)
                    steps["snapshot"]["ref"] = m.group(1) if m else None
        ref = steps.get("snapshot", {}).get("ref")
        if ref:
            click = subprocess.run(["playwright-cli", "click", ref],
                                   capture_output=True, text=True, timeout=60,
                                   env=env, cwd=workdir)
            steps["click"] = {"rc": click.returncode}
            snap2 = subprocess.run(["playwright-cli", "snapshot"],
                                   capture_output=True, text=True, timeout=60,
                                   env=env, cwd=workdir)
            ymls = sorted((workdir / ".playwright-cli").glob("page-*.yml"))
            content = ymls[-1].read_text(errors="replace") if ymls else ""
            steps["read"] = {"token_seen": "SMOKE-TOKEN-4F7A" in content}
        close = subprocess.run(["playwright-cli", "close"], capture_output=True,
                               text=True, timeout=60, env=env, cwd=workdir)
        steps["close"] = {"rc": close.returncode}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    ok = (steps.get("open", {}).get("rc") == 0
          and steps.get("snapshot", {}).get("ref_found")
          and steps.get("click", {}).get("rc") == 0
          and steps.get("read", {}).get("token_seen"))
    return {"route": "browser-cli", "ok": bool(ok),
            "status": "pass" if ok else "fail", "steps": steps}


def check_cli_psql(evidence, fixture_url):
    dsn = os.environ.get("TESTBED_PG_DSN")
    if not dsn:
        return {"route": "psql-cli", "ok": False, "status": "blocked",
                "detail": "TESTBED_PG_DSN not set"}
    proc = subprocess.run(["psql", dsn, "-tAc", "SELECT 'psql-ok'"],
                          capture_output=True, text=True, timeout=30)
    ok = proc.returncode == 0 and "psql-ok" in proc.stdout
    return {"route": "psql-cli", "ok": ok, "status": "pass" if ok else "fail",
            "error": None if ok else redact(proc.stderr[:200])}


def check_cli_gh(evidence, fixture_url):
    """Probe the dedicated study-account route (gh-github wrapper)."""
    if not shutil.which("gh-github"):
        return {"route": "gh-study-cli", "ok": False, "status": "blocked",
                "detail": "gh-github wrapper missing; run scripts/install-capabilities"}
    proc = subprocess.run(["gh-github", "api", "user", "--jq", ".login"],
                          capture_output=True, text=True, timeout=60)
    out = {"route": "gh-study-cli"}
    if proc.returncode != 0 or not proc.stdout.strip():
        err = redact(proc.stderr[:200]).lower()
        auth = "login" in err or "authenticate" in err or "browser" in err
        out.update(ok=False, status="auth-required" if auth else "fail",
                   error=redact(proc.stderr[:160]) or "empty response")
        return out
    out["authenticated"] = True
    expected = os.environ.get("GITHUB_EVAL_ORG")
    if expected:
        # Compare against the expected study login; never record the login itself.
        out["login_matches_env"] = proc.stdout.strip() == expected
        out["ok"] = out["login_matches_env"]
    else:
        out["ok"] = True
        out["detail"] = "GITHUB_EVAL_ORG unset; login match not checked"
    out["status"] = "pass" if out["ok"] else "fail"
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-dir", default=str(HERE / "evidence"))
    ap.add_argument("--fixture-url", default="http://127.0.0.1:5580/")
    ap.add_argument("--allow-unsandboxed-local-fixture", action="store_true",
                    help="Installation check ONLY against our trusted loopback fixture; not campaign-ready")
    ap.add_argument("--only", default=None,
                    help="comma list: brave,browser,postgres,github,bx,pwcli,psql,gh")
    args = ap.parse_args()
    if args.allow_unsandboxed_local_fixture and args.fixture_url != "http://127.0.0.1:5580/":
        ap.error("unsandboxed check restricted to the trusted local fixture URL")
    os.environ["PLAYWRIGHT_MCP_SANDBOX"] = (
        "false" if args.allow_unsandboxed_local_fixture else "true")
    evdir = Path(args.evidence_dir)
    evdir.mkdir(parents=True, exist_ok=True)
    only = args.only.split(",") if args.only else None
    checks = {
        "brave": lambda: check_brave(evdir, args.fixture_url),
        "browser": lambda: check_playwright_mcp(evdir, args.fixture_url),
        "postgres": lambda: check_postgres(evdir, args.fixture_url),
        "github": lambda: check_github(evdir, args.fixture_url),
        "bx": lambda: check_cli_bx(evdir, args.fixture_url),
        "pwcli": lambda: check_cli_playwright(evdir, args.fixture_url),
        "psql": lambda: check_cli_psql(evdir, args.fixture_url),
        "gh": lambda: check_cli_gh(evdir, args.fixture_url),
    }
    results = {}
    for name, fn in checks.items():
        if only and name not in only:
            continue
        print(f"probing {name} ...", flush=True)
        try:
            results[name] = fn()
        except Exception as exc:  # noqa: BLE001 — evidence must survive probes
            results[name] = {"ok": False, "status": "verifier_error",
                             "error": str(exc)[:200]}
        r = results[name]
        print(f"  -> {r.get('status')} ok={r.get('ok')}")
    evidence = {
        "schema": "capability-checks-v1",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fixture_url": args.fixture_url,
        "browser_sandbox_requested": not args.allow_unsandboxed_local_fixture,
        "notes": [
            "zero-model JSON-RPC probes of the pinned rig/runtime servers",
            "credentials passed via env only; values never recorded",
            "browser: pinned Google Chrome executable via PLAYWRIGHT_MCP_EXECUTABLE_PATH; sandbox setting recorded above",
            "a trusted-fixture unsandboxed pass is NOT campaign readiness",
        ],
        "results": redact(results),
    }
    out_path = evdir / "capabilities.json"
    out_path.write_text(json.dumps(evidence, indent=2) + "\n")
    print(f"evidence: {out_path}")
    return int(any(r.get("status") not in {"pass", "auth-required"}
                   for r in results.values()))


if __name__ == "__main__":
    sys.exit(main())
