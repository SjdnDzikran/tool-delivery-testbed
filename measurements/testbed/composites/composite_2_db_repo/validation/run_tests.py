#!/usr/bin/env python3
"""Validation for the composite_2_db_repo verifier.

Runs the verifier with a stub psql client (stub_psql.py, canned GROUP BY
aggregate) and --repo-file-override local stand-ins for the repository file,
so no PostgreSQL server, GitHub access, or network is needed. The live REST
mode is NOT exercised here and is environment-pending; see ../README.md.

Asserts the exit-code contract (0 pass, 1 incorrect, 2 incomplete,
3 missing_artifact, 4 verifier_error) and that the result JSON agrees with
the exit code. Exits nonzero if any scenario fails.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
VERIFY = os.path.join(HERE, os.pardir, "verify.py")
STUB = os.path.join(HERE, "stub_psql.py")
STUB_DSN = "postgres://stub:5432/testbed"  # the stub ignores it

VERDICTS = {0: "pass", 1: "incorrect", 2: "incomplete",
            3: "missing_artifact", 4: "verifier_error"}


def file_writer(text):
    """Writer placing text at <artifacts>/TOP_SELLER.md (override file)."""
    def _write(tmp):
        path = os.path.join(tmp, "TOP_SELLER.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    return _write


# (name, artifact writer or None, stub mode, expected exit code).
# None means the override file is absent (missing-artifact scenario).
SCENARIOS = [
    ("full_correct",                 file_writer("Aurora Lamp\n620\n"),
     "correct", 0),
    ("no_trailing_newline",          file_writer("Aurora Lamp\n620"),
     "correct", 0),
    ("wrong_product",                file_writer("Birch Desk\n620\n"),
     "correct", 1),
    ("wrong_total",                  file_writer("Aurora Lamp\n590\n"),
     "correct", 1),
    ("three_lines",                  file_writer("Aurora Lamp\n620\nRunner-up: Birch Desk\n"),
     "correct", 1),
    ("trailing_blank_line",          file_writer("Aurora Lamp\n620\n\n"),
     "correct", 1),
    ("non_integer_total",            file_writer("Aurora Lamp\n620 units\n"),
     "correct", 1),
    ("repo_file_missing",            None, "correct", 3),
    ("psql_stub_failure",            file_writer("Aurora Lamp\n620\n"),
     "error", 4),
    # The stub returns a different, self-consistent aggregate; a file
    # matching IT must pass, proving the expectation is computed from the
    # database rather than frozen in the verifier.
    ("expected_is_computed_not_frozen", file_writer("Birch Desk\n590\n"),
     "alt_product", 0),
]


def run_scenario(name, make_artifacts, stub_mode, expected_code):
    with tempfile.TemporaryDirectory() as tmp:
        if make_artifacts is not None:
            make_artifacts(tmp)
        env = os.environ.copy()
        env["STUB_SALES_MODE"] = stub_mode
        env["TESTBED_PG_DSN"] = STUB_DSN
        env.pop("TESTBED_GH_REPO", None)  # keep REST mode out of these runs
        override = os.path.join(tmp, "TOP_SELLER.md")
        result_path = os.path.join(tmp, "result.json")
        proc = subprocess.run(
            [sys.executable, VERIFY, "--artifacts", tmp,
             "--psql-cmd", f"{sys.executable} {STUB}",
             "--repo-file-override", override,
             "--result", result_path],
            env=env, capture_output=True, text=True, timeout=120)

        ok = proc.returncode == expected_code
        result = None
        if os.path.exists(result_path):
            with open(result_path, encoding="utf-8") as fh:
                result = json.load(fh)
            ok = ok and result.get("exit_code") == expected_code \
                and result.get("verdict") == VERDICTS[expected_code]
        else:
            ok = False

        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}: expected {expected_code} "
              f"({VERDICTS[expected_code]}), got {proc.returncode}")
        if not ok:
            print(f"    stdout: {proc.stdout.strip()[:400]}")
            print(f"    stderr: {proc.stderr.strip()[:400]}")
            if result is not None:
                print(f"    result: {json.dumps(result)[:400]}")
        return ok


def main() -> int:
    print(f"composite_2_db_repo validation: {len(SCENARIOS)} scenarios, "
          f"stub psql = {STUB}")
    print("NOTE: live GitHub REST mode is not exercised here "
          "(environment-pending; run on the rig).")
    failures = 0
    for name, writer, stub_mode, expected in SCENARIOS:
        if not run_scenario(name, writer, stub_mode, expected):
            failures += 1
    total = len(SCENARIOS)
    print(f"== composite_2_db_repo validation: {total - failures}/{total} "
          f"scenarios passed ==")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
