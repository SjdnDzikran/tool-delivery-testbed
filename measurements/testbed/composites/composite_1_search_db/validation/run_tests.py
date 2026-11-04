#!/usr/bin/env python3
"""Validation for the composite_1_search_db verifier.

Runs the verifier against temporary artifact directories with a stub psql
client (stub_psql.py), so no PostgreSQL server and no network are needed.
Live-DB behaviour is environment-pending; see ../README.md.

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

WIKI_URL = "https://en.wikipedia.org/wiki/Grace_Hopper"
VERDICTS = {0: "pass", 1: "incorrect", 2: "incomplete",
            3: "missing_artifact", 4: "verifier_error"}


def evidence(value="1906", url=WIKI_URL, with_sources=True, quote=None,
             fact="birth_year_grace_hopper", raw=None):
    """Build a scenario's evidence.json content (dict or raw text)."""
    if raw is not None:
        return raw
    obj = {"fact": fact, "value": value}
    if with_sources:
        if quote is None:
            quote = ("Grace Hopper was born on December 9, 1906, "
                     "in New York City.")
        obj["sources"] = [{"url": url, "quote": quote}]
    return obj


def write_json(content):
    """Writer placing content (dict or str) at <artifacts>/evidence.json."""
    def _write(tmp):
        path = os.path.join(tmp, "evidence.json")
        with open(path, "w", encoding="utf-8") as fh:
            if isinstance(content, str):
                fh.write(content)
            else:
                json.dump(content, fh, indent=2)
    return _write


# (name, artifact writer or None, stub mode, expected exit code)
SCENARIOS = [
    ("full_correct",          write_json(evidence()), "correct", 0),
    ("wrong_year_in_evidence", write_json(evidence(value="1907")), "correct", 1),
    ("quote_without_year",    write_json(evidence(
        quote="Grace Hopper was a pioneering computer scientist and "
              "United States Navy rear admiral.")), "correct", 1),
    ("insecure_url",          write_json(evidence(
        url="http://en.wikipedia.org/wiki/Grace_Hopper")), "correct", 1),
    ("missing_sources_key",   write_json(evidence(with_sources=False)),
     "correct", 2),
    ("empty_sources_list",    write_json(evidence() | {"sources": []}),
     "correct", 2),
    ("malformed_json",        write_json("{not valid json"), "correct", 2),
    ("missing_evidence_file", None, "correct", 3),
    ("db_row_missing",        write_json(evidence()), "no_row", 3),
    ("db_value_mismatch",     write_json(evidence()), "wrong_value", 1),
    ("db_url_mismatch",       write_json(evidence()), "wrong_url", 1),
    ("db_duplicate_rows",     write_json(evidence()), "duplicate", 1),
    ("stub_connection_error", write_json(evidence()), "error", 4),
]


def run_scenario(name, make_artifacts, stub_mode, expected_code):
    with tempfile.TemporaryDirectory() as tmp:
        if make_artifacts is not None:
            make_artifacts(tmp)
        env = os.environ.copy()
        env["STUB_FACTS_MODE"] = stub_mode
        env["TESTBED_PG_DSN"] = STUB_DSN
        result_path = os.path.join(tmp, "result.json")
        proc = subprocess.run(
            [sys.executable, VERIFY, "--artifacts", tmp,
             "--psql-cmd", f"{sys.executable} {STUB}",
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
    print(f"composite_1_search_db validation: {len(SCENARIOS)} scenarios, "
          f"stub psql = {STUB}")
    failures = 0
    for name, writer, stub_mode, expected in SCENARIOS:
        if not run_scenario(name, writer, stub_mode, expected):
            failures += 1
    total = len(SCENARIOS)
    print(f"== composite_1_search_db validation: {total - failures}/{total} "
          f"scenarios passed ==")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
