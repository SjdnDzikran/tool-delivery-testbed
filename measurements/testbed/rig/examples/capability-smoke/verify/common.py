#!/usr/bin/env python3
"""Shared helpers for capability-smoke verifiers.
Exit codes follow testbed/common/verify_lib.py; a
capability-smoke pass proves route reachability, NOT task equivalence.
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, os.pardir, os.pardir, os.pardir, "common")))

from verify_lib import (  # noqa: E402,F401  (re-exported for verifiers)
    INCORRECT,
    INCOMPLETE,
    MISSING_ARTIFACT,
    PASS,
    VERIFIER_ERROR,
    check,
    die,
    load_json_file,
    write_result,
)


def parse_artifacts(argv: list[str]) -> str:
    artifacts = None
    i = 0
    while i < len(argv):
        if argv[i] == "--artifacts" and i + 1 < len(argv):
            artifacts = argv[i + 1]
            i += 2
        else:
            die(VERIFIER_ERROR, f"unexpected argument {argv[i]!r}; "
                "usage: python3 verify.py --artifacts DIR")
    if not artifacts:
        die(VERIFIER_ERROR, "missing --artifacts DIR")
    return artifacts


def finish(task_id: str, artifacts_dir: str, checks: list[dict]) -> int:
    ok = all(c["passed"] for c in checks)
    write_result(os.path.join(artifacts_dir, "verification.json"), task_id,
                 PASS if ok else INCORRECT, checks)
    for c in checks:
        print(f"[{'ok' if c['passed'] else 'FAIL'}] {c['name']}: {c['detail']}")
    return PASS if ok else INCORRECT
