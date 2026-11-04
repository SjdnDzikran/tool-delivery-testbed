#!/usr/bin/env python3
"""Verifier for the verification canary task [ours].

Pass: artifacts/result.txt contains exactly one non-empty line equal to
"CANARY_ECHO_OK: ping" (trailing whitespace tolerated).
Exit codes follow testbed/common/verify_lib.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

EXPECTED = "CANARY_ECHO_OK: ping"


def main() -> int:
    artifacts = Path(sys.argv[sys.argv.index("--artifacts") + 1]) \
        if "--artifacts" in sys.argv else Path(".")
    result = artifacts / "result.txt"
    if not result.is_file():
        print(json.dumps({"verdict": "missing",
                          "detail": f"{result} not found"}))
        return 3
    lines = [ln.strip() for ln in result.read_text(
        encoding="utf-8", errors="replace").splitlines() if ln.strip()]
    if lines == [EXPECTED]:
        print(json.dumps({"verdict": "pass", "detail": "exact canary line"}))
        return 0
    detail = (f"expected [{EXPECTED!r}], got {lines[:3]!r}")
    verdict = "incorrect" if lines else "incomplete"
    print(json.dumps({"verdict": verdict, "detail": detail}))
    return {"incorrect": 1, "incomplete": 2}[verdict]


if __name__ == "__main__":
    sys.exit(main())
