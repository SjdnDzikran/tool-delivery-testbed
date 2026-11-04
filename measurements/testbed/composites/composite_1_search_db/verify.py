#!/usr/bin/env python3
"""Verifier for composite task 1 (web search -> database record) [ours].

Route-neutral: it inspects only the agent's evidence.json and the resulting
PostgreSQL state, read through a psql client. It never invokes the compared
delivery routes (Brave MCP / bx CLI, or any agent-side database route).

Frozen reference: Grace Hopper's birth year is 1906 (stable encyclopedic
fact, frozen before the pilot). The database check reads the row via

    SELECT row_to_json(q) FROM (SELECT label, value, source_url
                                FROM public.facts
                                WHERE label = 'birth_year_grace_hopper') q;

(the reference SELECT wrapped in row_to_json so psql emits one JSON object
per matching row, which also makes the exactly-one-row check direct).

Live-DB validation is environment-pending: in environments without a
reachable PostgreSQL server, pass --psql-cmd to inject a stub client
(see validation/run_tests.py).

Exit codes follow common/verify_lib.py: 0 pass, 1 incorrect, 2 incomplete,
3 missing_artifact, 4 verifier_error. A verifier error (4) overrides content
verdicts, because a broken environment invalidates the whole run; otherwise
the FIRST failing check in execution order decides the exit code.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, os.pardir, "common"))

from verify_lib import (  # noqa: E402
    INCORRECT,
    INCOMPLETE,
    MISSING_ARTIFACT,
    PASS,
    VERIFIER_ERROR,
    answers_equal,
    check,
    die,
    normalize_text,
)

TASK_ID = "composite_1_search_db"
EXPECTED_FACT = "birth_year_grace_hopper"
EXPECTED_YEAR = "1906"  # frozen reference [ours]
FACTS_QUERY = (
    "SELECT row_to_json(q) FROM (SELECT label, value, source_url "
    "FROM public.facts WHERE label = 'birth_year_grace_hopper') q;"
)


def run_psql(psql_cmd: str, dsn: str, sql: str) -> tuple[bool, str, str]:
    """Run one SQL statement through the configured psql client.

    Returns (ok, stdout, failure_detail). Never raises."""
    cmd = shlex.split(psql_cmd) + [
        "-X", "-At", "-q", "-v", "ON_ERROR_STOP=1", "-d", dsn, "-c", sql,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        return False, "", f"psql command not found: {psql_cmd!r}"
    except subprocess.TimeoutExpired:
        return False, "", "psql timed out after 60s"
    if proc.returncode != 0:
        err_lines = (proc.stderr or proc.stdout or "").strip().splitlines()
        last = err_lines[-1] if err_lines else "(no output)"
        return False, "", f"psql exited {proc.returncode}: {last}"
    return True, proc.stdout, ""


def finish(records: list[tuple[dict, int]], result_path: str, message: str) -> None:
    """Compute the final exit code, write the result JSON, and exit.

    Rule: a verifier error (4) overrides content verdicts (the environment
    invalidates the run); otherwise the first failing check decides."""
    fail_codes = [code for chk, code in records if not chk["passed"]]
    if VERIFIER_ERROR in fail_codes:
        code = VERIFIER_ERROR
    elif fail_codes:
        code = fail_codes[0]
    else:
        code = PASS
    n_pass = sum(1 for chk, _ in records if chk["passed"])
    die(code, f"{n_pass}/{len(records)} checks passed - {message}",
        result_path, TASK_ID, [chk for chk, _ in records])


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Verifier for composite_1_search_db [ours].")
    ap.add_argument("--artifacts", required=True,
                    help="directory containing the agent's evidence.json")
    ap.add_argument("--psql-cmd", default="psql",
                    help="psql client invocation; validation injects a stub")
    ap.add_argument("--dsn", default=None,
                    help="PostgreSQL DSN (defaults to env TESTBED_PG_DSN)")
    ap.add_argument("--result", default="verify_result.json",
                    help="path for the machine-readable result JSON")
    args = ap.parse_args()

    evidence_path = os.path.join(args.artifacts, "evidence.json")
    records: list[tuple[dict, int]] = []  # (check, code if this check fails)

    def record(name: str, passed: bool, fail_code: int, detail: str = "") -> None:
        records.append((check(name, passed, detail), fail_code))

    # (a) artifact presence, JSON validity, required structure
    if not os.path.isfile(evidence_path):
        record("evidence_file_exists", False, MISSING_ARTIFACT, evidence_path)
        finish(records, args.result, "evidence.json is missing")
    record("evidence_file_exists", True, MISSING_ARTIFACT, evidence_path)

    try:
        with open(evidence_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        record("evidence_json_valid", False, INCOMPLETE, f"not valid JSON: {exc}")
        finish(records, args.result, "evidence.json is not valid JSON")
    record("evidence_json_valid", True, INCOMPLETE)

    if not isinstance(data, dict):
        record("evidence_required_fields", False, INCOMPLETE,
               "top level is not a JSON object")
        finish(records, args.result, "evidence.json must be a JSON object")
    missing = [k for k in ("fact", "value", "sources") if k not in data]
    if missing:
        record("evidence_required_fields", False, INCOMPLETE,
               f"missing fields: {', '.join(missing)}")
        finish(records, args.result,
               f"evidence.json is missing required fields: {missing}")
    record("evidence_required_fields", True, INCOMPLETE)

    sources = data["sources"]
    if not isinstance(sources, list) or not sources:
        record("evidence_sources_present", False, INCOMPLETE,
               "'sources' must be a non-empty list")
        finish(records, args.result, "evidence.json has no sources")
    record("evidence_sources_present", True, INCOMPLETE,
           f"{len(sources)} source(s) listed")

    # (b) fact label and value against the frozen reference
    record("evidence_fact_label",
           answers_equal(EXPECTED_FACT, str(data["fact"])), INCORRECT,
           f"fact={data['fact']!r}, expected {EXPECTED_FACT!r}")
    record("evidence_value_matches",
           answers_equal(EXPECTED_YEAR, str(data["value"])), INCORRECT,
           f"value={data['value']!r}, expected {EXPECTED_YEAR!r}")

    # (c) evidentiary support: at least one source with a well-formed https
    # URL and a non-empty quote whose normalized text contains the year.
    # The primary source is sources[0]; the DB row's source_url must repeat it.
    support_ok = False
    problems: list[str] = []
    primary_url = ""
    for i, src in enumerate(sources):
        if not isinstance(src, dict):
            problems.append(f"source[{i}]: not an object")
            continue
        url = src.get("url")
        quote = src.get("quote")
        parsed = urlparse(url) if isinstance(url, str) else None
        url_ok = bool(parsed and parsed.scheme == "https" and parsed.netloc)
        quote_ok = (isinstance(quote, str) and bool(quote.strip())
                    and EXPECTED_YEAR in normalize_text(quote))
        if url_ok and quote_ok:
            support_ok = True
        else:
            problems.append(f"source[{i}]: url_ok={url_ok}, quote_ok={quote_ok}")
        if i == 0 and isinstance(url, str):
            primary_url = url.strip()
    record("evidence_support", support_ok, INCORRECT,
           "; ".join(problems) if problems else
           "at least one source supports the year")

    # (d) database state, read through the psql client (route-neutral)
    dsn = args.dsn or os.environ.get("TESTBED_PG_DSN", "")
    if not dsn:
        record("db_query_executed", False, VERIFIER_ERROR,
               "no DSN available: pass --dsn or set TESTBED_PG_DSN")
        finish(records, args.result, "verifier could not reach the database")
    ok, out, detail = run_psql(args.psql_cmd, dsn, FACTS_QUERY)
    if not ok:
        record("db_query_executed", False, VERIFIER_ERROR, detail)
        finish(records, args.result, f"database query failed: {detail}")
    record("db_query_executed", True, VERIFIER_ERROR,
           "SELECT over public.facts completed")

    rows = [ln for ln in out.splitlines() if ln.strip()]
    if not rows:
        record("db_row_present", False, MISSING_ARTIFACT,
               "no row with label 'birth_year_grace_hopper' in public.facts")
        finish(records, args.result, "database row is missing")
    try:
        parsed_rows = [json.loads(ln) for ln in rows]
    except json.JSONDecodeError as exc:
        record("db_row_present", False, VERIFIER_ERROR,
               f"could not parse psql output as JSON rows: {exc}")
        finish(records, args.result, f"could not parse psql output: {exc}")
    record("db_row_present", True, MISSING_ARTIFACT,
           f"{len(parsed_rows)} row(s) found")
    if len(parsed_rows) > 1:
        record("db_row_unique", False, INCORRECT,
               f"{len(parsed_rows)} rows carry the label; expected exactly one")
        finish(records, args.result, "duplicate database rows")
    record("db_row_unique", True, INCORRECT, "exactly one row")

    row = parsed_rows[0]
    if not isinstance(row, dict) or "value" not in row:
        record("db_value_matches", False, VERIFIER_ERROR,
               "row is not a JSON object with a 'value' field")
        finish(records, args.result, "unexpected row shape from psql")
    record("db_value_matches",
           answers_equal(EXPECTED_YEAR, str(row["value"])), INCORRECT,
           f"db value={row['value']!r}, expected {EXPECTED_YEAR!r}")
    db_url = row.get("source_url")
    record("db_source_url_matches",
           isinstance(db_url, str) and bool(primary_url)
           and db_url.strip() == primary_url, INCORRECT,
           f"db source_url={db_url!r} vs evidence primary={primary_url!r}")

    finish(records, args.result, "composite_1_search_db verification completed")


if __name__ == "__main__":
    main()
