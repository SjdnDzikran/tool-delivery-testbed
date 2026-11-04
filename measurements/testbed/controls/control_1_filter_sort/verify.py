#!/usr/bin/env python3
"""Verifier for control_1_filter_sort [ours -- proposed, pending student
approval and pilot freeze].

Usage: python3 verify.py --artifacts DIR

Checks DIR/result.json (the agent's answer) against expected/result.json
(computed once by ref_solve.py from fixtures/records.json). Writes a
machine-readable report to DIR/verification.json. Exit codes follow
common/verify_lib.py: 0 pass, 1 incorrect, 2 incomplete, 3 missing
artifact, 4 verifier error. Route compliance is audited separately from
session transcripts; this verifier only inspects the artifact.
"""
from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, os.pardir, os.pardir, "common")))

from verify_lib import (  # noqa: E402
    INCORRECT,
    INCOMPLETE,
    MISSING_ARTIFACT,
    PASS,
    VERIFIER_ERROR,
    check,
    deep_equal,
    die,
    load_json_file,
)

TASK_ID = "control_1_filter_sort"
KEY_ORDER = ["id", "name", "salary"]


def _require_testbed() -> str:
    """The verifier depends only on these two committed testbed files."""
    expected_path = os.path.join(_HERE, "expected", "result.json")
    records_path = os.path.join(_HERE, "fixtures", "records.json")
    for path in (expected_path, records_path):
        if not os.path.isfile(path):
            die(VERIFIER_ERROR, f"testbed file missing: {path}")
    return expected_path


def _parse_artifacts(argv: list[str]) -> str:
    artifacts = None
    i = 0
    while i < len(argv):
        if argv[i] == "--artifacts" and i + 1 < len(argv):
            artifacts = argv[i + 1]
            i += 2
        else:
            die(VERIFIER_ERROR,
                f"unexpected argument {argv[i]!r}; usage: python3 verify.py --artifacts DIR")
    if not artifacts:
        die(VERIFIER_ERROR,
            "missing required --artifacts DIR; usage: python3 verify.py --artifacts DIR")
    return artifacts


def _structural_checks(artifact, checks: list[dict]) -> bool:
    """Shape, keys (exact set and order), and types; one check entry each."""
    ok = True
    if not isinstance(artifact, list):
        checks.append(check("top-level shape is a JSON array", False,
                            f"got {type(artifact).__name__}"))
        return False
    checks.append(check("top-level shape is a JSON array", True))

    for i, row in enumerate(artifact):
        label = f"row[{i}]"
        if not isinstance(row, dict):
            checks.append(check(f"{label} is a JSON object", False,
                                f"got {type(row).__name__}"))
            ok = False
            continue
        keys = list(row.keys())
        if keys != KEY_ORDER:
            checks.append(check(f"{label} has exactly the keys {KEY_ORDER} in order",
                                False, f"got {keys}"))
            ok = False
        else:
            checks.append(check(f"{label} has exactly the keys {KEY_ORDER} in order", True))
        for key in ("id", "name"):
            value = row.get(key)
            if not isinstance(value, str):
                checks.append(check(f"{label}.{key} is a string", False, f"got {value!r}"))
                ok = False
        salary = row.get("salary")
        if isinstance(salary, bool) or not isinstance(salary, (int, float)):
            checks.append(check(f"{label}.salary is a JSON number", False, f"got {salary!r}"))
            ok = False
    return ok


def main() -> None:
    expected_path = _require_testbed()
    artifacts_dir = os.path.abspath(_parse_artifacts(sys.argv[1:]))
    report_path = os.path.join(artifacts_dir, "verification.json")

    if not os.path.isdir(artifacts_dir):
        die(MISSING_ARTIFACT, f"artifacts directory not found: {artifacts_dir}")

    try:
        with open(expected_path, encoding="utf-8") as fh:
            expected = json.load(fh)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        die(VERIFIER_ERROR, f"cannot load expected result: {exc}", report_path, TASK_ID)
    if not isinstance(expected, list):
        die(VERIFIER_ERROR, "expected/result.json is not a JSON array", report_path, TASK_ID)

    artifact = load_json_file(os.path.join(artifacts_dir, "result.json"),
                              report_path, TASK_ID)

    checks: list[dict] = []
    if _structural_checks(artifact, checks):
        matched, why = deep_equal(expected, artifact)
        checks.append(check("values match expected/result.json", matched, why))
        if not matched:
            die(INCORRECT, f"value mismatch: {why}", report_path, TASK_ID, checks)
        die(PASS, "result.json matches the expected result", report_path, TASK_ID, checks)
    die(INCOMPLETE, "structural checks failed; see checks in verification.json",
        report_path, TASK_ID, checks)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # an unexpected verifier bug must never read as "incorrect"
        die(VERIFIER_ERROR, f"verifier error: {exc!r}")
