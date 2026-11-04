#!/usr/bin/env python3
"""Verifier for composite task 2 (database -> repository publish) [ours].

Route-neutral: it recomputes the expected answer ITSELF from the database via
reference SQL through a psql client, then inspects the published file. It
never invokes the compared delivery routes (PostgreSQL MCP / any agent-side
database route, GitHub MCP / gh CLI).

No frozen answer: the expected (product, total) pair is computed at
verification time from public.product_sales with

    SELECT product, SUM(units) AS total FROM public.product_sales
    GROUP BY product ORDER BY total DESC LIMIT 1;

and is recorded in the result JSON (verifier outputs are safe to record).

Published-file access:
  * --repo-file-override PATH reads a local file standing in for the repo
    file (used by validation and available for offline rigs);
  * otherwise the file is fetched live via the GitHub REST contents API
    (stdlib urllib, env GITHUB_TOKEN, GET /repos/{repo}/contents/TOP_SELLER.md,
    base64-decoded). This is the only network call in this verifier and is
    documented; live REST is environment-pending and not exercised here.

Exit codes follow common/verify_lib.py: 0 pass, 1 incorrect, 2 incomplete,
3 missing_artifact, 4 verifier_error. A verifier error (4) overrides content
verdicts; otherwise the FIRST failing check in execution order decides.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shlex
import subprocess
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, os.pardir, "common"))

from verify_lib import (  # noqa: E402
    INCORRECT,
    MISSING_ARTIFACT,
    PASS,
    VERIFIER_ERROR,
    answers_equal,
    check,
    die,
)

TASK_ID = "composite_2_db_repo"
FILE_NAME = "TOP_SELLER.md"
REFERENCE_SQL = ("SELECT product, SUM(units) AS total FROM public.product_sales "
                 "GROUP BY product ORDER BY total DESC LIMIT 1;")


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


def fetch_repo_file(repo: str) -> tuple[str | None, int, str]:
    """Fetch TOP_SELLER.md from the repo's default branch via GitHub REST.

    Returns (content, code, detail): code 0 on success, 3 if the file is
    absent (HTTP 404), 4 on any other API/network/decoding failure."""
    url = f"https://api.github.com/repos/{repo}/contents/{FILE_NAME}"
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "testbed-verifier"}
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None, MISSING_ARTIFACT, (
                f"{FILE_NAME} not found on the default branch (HTTP 404)")
        return None, VERIFIER_ERROR, f"GitHub API HTTP error {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError,
            json.JSONDecodeError, KeyError) as exc:
        return None, VERIFIER_ERROR, f"GitHub API request failed: {exc}"
    raw = payload.get("content")
    if raw is None:
        return None, VERIFIER_ERROR, (
            "GitHub API returned no inline content "
            "(file too large for the contents API)")
    try:
        return base64.b64decode(raw).decode("utf-8"), PASS, \
            "fetched via GitHub REST contents API"
    except (ValueError, UnicodeDecodeError) as exc:
        return None, VERIFIER_ERROR, f"could not decode file content: {exc}"


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
        description="Verifier for composite_2_db_repo [ours].")
    ap.add_argument("--artifacts", required=True,
                    help="kept for interface symmetry; the graded artifact "
                         "is the repository file, not a local one")
    ap.add_argument("--psql-cmd", default="psql",
                    help="psql client invocation; validation injects a stub")
    ap.add_argument("--dsn", default=None,
                    help="PostgreSQL DSN (defaults to env TESTBED_PG_DSN)")
    ap.add_argument("--repo", default=None,
                    help="repository as owner/name "
                         "(defaults to env TESTBED_GH_REPO; live REST only)")
    ap.add_argument("--repo-file-override", default=None,
                    help="local file standing in for the repo file "
                         "(tests/offline rigs; skips the REST call)")
    ap.add_argument("--result", default="verify_result.json",
                    help="path for the machine-readable result JSON")
    args = ap.parse_args()

    records: list[tuple[dict, int]] = []  # (check, code if this check fails)

    def record(name: str, passed: bool, fail_code: int, detail: str = "") -> None:
        records.append((check(name, passed, detail), fail_code))

    # Step 1: compute the expected answer from the database (reference SQL).
    dsn = args.dsn or os.environ.get("TESTBED_PG_DSN", "")
    if not dsn:
        record("reference_db_query", False, VERIFIER_ERROR,
               "no DSN available: pass --dsn or set TESTBED_PG_DSN")
        finish(records, args.result, "verifier could not reach the database")
    ok, out, detail = run_psql(args.psql_cmd, dsn, REFERENCE_SQL)
    if not ok:
        record("reference_db_query", False, VERIFIER_ERROR, detail)
        finish(records, args.result, f"reference query failed: {detail}")
    record("reference_db_query", True, VERIFIER_ERROR,
           "reference GROUP BY aggregate completed")

    lines = [ln for ln in out.splitlines() if ln.strip()]
    if len(lines) != 1:
        record("reference_parsed", False, VERIFIER_ERROR,
               f"expected exactly one aggregate row, got {len(lines)}")
        finish(records, args.result,
               f"unexpected reference output ({len(lines)} rows)")
    product, sep, total_text = lines[0].rpartition("|")
    total_text = total_text.strip()
    if not sep or not product.strip() or not re.fullmatch(r"\d+", total_text):
        record("reference_parsed", False, VERIFIER_ERROR,
               f"could not parse aggregate row {lines[0]!r}")
        finish(records, args.result, "could not parse reference output")
    expected_product = product.strip()
    expected_total = int(total_text)
    # The computed pair is recorded: expected values are verifier outputs.
    record("reference_parsed", True, VERIFIER_ERROR,
           f"expected (product={expected_product!r}, total={expected_total})")

    # Step 2: obtain the published file (override or live REST).
    if args.repo_file_override:
        if not os.path.isfile(args.repo_file_override):
            record("repo_file_obtained", False, MISSING_ARTIFACT,
                   f"{FILE_NAME} not found at override path "
                   f"{args.repo_file_override}")
            finish(records, args.result,
                   f"{FILE_NAME} is missing (override path)")
        with open(args.repo_file_override, encoding="utf-8") as fh:
            content = fh.read()
        record("repo_file_obtained", True, MISSING_ARTIFACT,
               f"read from override {args.repo_file_override}")
    else:
        repo = args.repo or os.environ.get("TESTBED_GH_REPO", "")
        if not repo:
            record("repo_file_obtained", False, VERIFIER_ERROR,
                   "no repository available: pass --repo or set TESTBED_GH_REPO")
            finish(records, args.result, "verifier has no repository to check")
        content, code, detail = fetch_repo_file(repo)
        record("repo_file_obtained", code == PASS, code, detail)
        if content is None:
            finish(records, args.result, f"could not obtain {FILE_NAME}: {detail}")

    # Step 3: content checks (exactly two lines, product, integer total).
    raw_lines = content.split("\n")
    if raw_lines and raw_lines[-1] == "":
        raw_lines = raw_lines[:-1]  # a single trailing newline is normal
    raw_lines = [ln[:-1] if ln.endswith("\r") else ln for ln in raw_lines]
    record("file_two_lines", len(raw_lines) == 2, INCORRECT,
           f"{len(raw_lines)} content line(s), expected exactly 2")
    if len(raw_lines) != 2:
        finish(records, args.result, f"{FILE_NAME} does not have exactly two lines")
    record("product_matches",
           answers_equal(expected_product, raw_lines[0].strip()), INCORRECT,
           f"line 1={raw_lines[0]!r}, expected product {expected_product!r}")
    line2 = raw_lines[1].strip()
    record("total_matches",
           re.fullmatch(r"\d+", line2) is not None
           and int(line2) == expected_total, INCORRECT,
           f"line 2={raw_lines[1]!r}, expected total {expected_total}")

    finish(records, args.result, "composite_2_db_repo verification completed")


if __name__ == "__main__":
    main()
