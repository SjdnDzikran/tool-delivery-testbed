#!/usr/bin/env python3
"""Self-tests for verify_gaia.py against static fixtures (stdlib only).

Status: [ours — frozen before the campaign]. Run from anywhere:

    python3 gaia/validation/run_tests.py

Each case runs verify_gaia.py in a subprocess against
fixtures/<case>/ and asserts the exit code (0 pass, 1 incorrect,
2 incomplete, 3 missing_artifact, 4 verifier_error), the verdict in the
result JSON, and — where relevant — which named check failed. Prints
PASS/FAIL per case; exits nonzero if any case fails. Result JSONs go to a
temp directory so the fixture tree stays clean.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERIFIER = HERE.parent / "verify_gaia.py"
FIXTURES = HERE / "fixtures"

# case -> (expected exit code, expected verdict, expected failed check or None)
CASES = {
    "known_correct":              (0, "pass", None),
    "abbreviated_quote":          (0, "pass", None),
    "known_correct_transcript":   (0, "pass", None),
    "wrong_answer":               (1, "incorrect", "answer_matches_reference"),
    "empty_sources":              (2, "incomplete", "sources_valid"),
    "unsupporting_quote":         (1, "incorrect", "evidence_support"),
    "missing_answer_json":        (3, "missing_artifact", None),
    "route_evidence_missing_url": (1, "incorrect", "route_evidence"),
    "malformed_task":             (4, "verifier_error", None),
}


def run_case(case: str, tmp: Path) -> tuple[bool, str]:
    fdir = FIXTURES / case
    cmd = [sys.executable, str(VERIFIER),
           "--artifacts", str(fdir),
           "--task", str(fdir / "task.json"),
           "--out", str(tmp / f"{case}.json")]
    transcript = fdir / "transcript.jsonl"
    if transcript.exists():
        cmd += ["--transcript", str(transcript)]

    expected_code, expected_verdict, expected_failed = CASES[case]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

    problems = []
    if proc.returncode != expected_code:
        problems.append(f"exit {proc.returncode} != {expected_code} "
                        f"(stderr: {proc.stderr.strip()[:200]})")

    result_file = tmp / f"{case}.json"
    if result_file.exists():
        result = json.loads(result_file.read_text(encoding="utf-8"))
        if result.get("verdict") != expected_verdict:
            problems.append(f"verdict {result.get('verdict')!r} != "
                            f"{expected_verdict!r}")
        if expected_failed is not None:
            entry = next((c for c in result.get("checks", [])
                          if c.get("check") == expected_failed), None)
            if entry is None:
                problems.append(f"check {expected_failed!r} not recorded")
            elif entry.get("passed") is not False:
                problems.append(f"check {expected_failed!r} not failed: "
                                f"{entry}")
    else:
        problems.append(f"result JSON not written: {result_file}")

    if problems:
        return False, "; ".join(problems)
    return True, f"exit={expected_code} verdict={expected_verdict}" + (
        f" failed_check={expected_failed}" if expected_failed else "")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="gaia-verify-tests-") as tmp:
        failures = 0
        for case in CASES:
            ok, detail = run_case(case, Path(tmp))
            print(f"[{'PASS' if ok else 'FAIL'}] {case}: {detail}")
            failures += 0 if ok else 1

        # transcript-omitted behavior: route_evidence must be recorded as skipped
        fdir = FIXTURES / "known_correct"
        out = Path(tmp) / "skipped_route.json"
        subprocess.run([sys.executable, str(VERIFIER),
                        "--artifacts", str(fdir),
                        "--task", str(fdir / "task.json"),
                        "--out", str(out)],
                       capture_output=True, text=True, timeout=60)
        result = json.loads(out.read_text(encoding="utf-8"))
        route = next((c for c in result["checks"]
                      if c.get("check") == "route_evidence"), None)
        if result["verdict"] == "pass" and route and route.get("skipped"):
            print("[PASS] transcript_omitted: verdict=pass, "
                  "route_evidence recorded as skipped")
        else:
            print(f"[FAIL] transcript_omitted: verdict={result['verdict']}, "
                  f"route_evidence={route}")
            failures += 1

        total = len(CASES) + 1
        print(f"\n{total - failures}/{total} cases passed")
        sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
