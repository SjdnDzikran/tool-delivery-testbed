#!/usr/bin/env python3
"""Verifier for the browser capability smoke [ours]."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import INCORRECT, MISSING_ARTIFACT, check, finish, parse_artifacts  # noqa: E402

TASK_ID = "cap_browser"
EXPECTED = "SMOKE-TOKEN-4F7A"


def main() -> int:
    artifacts = parse_artifacts(sys.argv[1:])
    checks = []
    token_path = os.path.join(artifacts, "token.txt")
    if not os.path.isfile(token_path):
        checks.append(check("token.txt exists", False, "missing"))
        return finish(TASK_ID, artifacts, checks)
    checks.append(check("token.txt exists", True))
    raw = open(token_path, encoding="utf-8", errors="replace").read()
    got = raw.strip()
    checks.append(check("token matches the fixture answer", got == EXPECTED,
                        f"got {got[:40]!r}"))
    return finish(TASK_ID, artifacts, checks)


if __name__ == "__main__":
    sys.exit(main())
