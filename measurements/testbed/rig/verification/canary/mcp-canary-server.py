#!/usr/bin/env python3
"""Minimal stdio MCP canary server for rig verification [ours].

Stdlib-only, newline-delimited JSON-RPC 2.0 (MCP stdio transport). One tool:
`canary_echo` returns "CANARY_ECHO_OK: <text>". Run with --server decoy to
serve the decoy variant (`decoy_frobnicate` / "DECOY_FROBNICATE_OK") used to
prove the full-vs-required catalog difference. Purely local: no network, no
state, read-only by construction.
"""
import argparse
import json
import sys

PROTOCOL_VERSION = "2025-06-18"


def build_server(name: str) -> dict:
    if name == "canary":
        return {
            "name": "canary",
            "instructions": "Verification canary server. Tool canary_echo echoes text back prefixed with CANARY_ECHO_OK.",
            "tools": [{
                "name": "canary_echo",
                "description": "Echo the given text prefixed with CANARY_ECHO_OK. Verification canary only.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"text": {"type": "string",
                                            "description": "Text to echo."}},
                    "required": ["text"],
                },
            }],
        }
    return {
        "name": "decoy",
        "instructions": "Verification decoy server. Must never be required by a task; used to prove catalog-size differences.",
        "tools": [{
            "name": "decoy_frobnicate",
            "description": "DECOY capability that must only be declared in full-catalog trials.",
            "inputSchema": {"type": "object", "properties": {},
                            "required": []},
        }],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", choices=("canary", "decoy"), default="canary")
    args = ap.parse_args()
    server = build_server(args.server)
    marker = ("CANARY_ECHO_OK: " if args.server == "canary"
              else "DECOY_FROBNICATE_OK: ")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = req.get("method")
        rid = req.get("id")
        if rid is None:
            continue  # notification: nothing to answer
        if method == "initialize":
            result = {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": server["name"], "version": "1.0.0"},
                "instructions": server["instructions"],
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": server["tools"]}
        elif method == "tools/call":
            params = req.get("params") or {}
            tname = params.get("name")
            targs = params.get("arguments") or {}
            if args.server == "canary" and tname == "canary_echo":
                text = "CANARY_ECHO_OK: " + str(targs.get("text", ""))
                result = {"content": [{"type": "text", "text": text}],
                          "isError": False}
            elif args.server == "decoy" and tname == "decoy_frobnicate":
                result = {"content": [{"type": "text", "text": marker + "done"}],
                          "isError": False}
            else:
                result = {"content": [{"type": "text",
                                       "text": f"unknown tool {tname!r}"}],
                          "isError": True}
        else:
            req_obj = {"jsonrpc": "2.0", "id": rid,
                       "error": {"code": -32601,
                                 "message": f"method not found: {method}"}}
            sys.stdout.write(json.dumps(req_obj) + "\n")
            sys.stdout.flush()
            continue
        resp = {"jsonrpc": "2.0", "id": rid, "result": result}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
