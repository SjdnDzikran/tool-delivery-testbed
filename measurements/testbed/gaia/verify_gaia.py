#!/usr/bin/env python3
"""Verifier for GAIA-derived web-search tasks (capability pair: Brave Search
MCP vs `bx` CLI).

Status: [ours — acceptance rules frozen before the campaign].

Usage:
    python3 verify_gaia.py --artifacts DIR --task gaia_tasks/<task_id>.json \
        [--transcript SESSION.jsonl] [--out RESULT.json]

Task JSON schema: {"task_id", "question", "reference_answer", "provenance"}.
Agent artifact contract: DIR/answer.json =
    {"answer": str, "sources": [{"url": str, "quote": str}, ...]}

Acceptance rules (checked in order; the first failing check decides the
verdict, checks after it are recorded as skipped):

  a. answer_matches_reference — the artifact answer equals the task's
     reference answer via verify_lib.answers_equal (exact, normalized, or
     numeric equality). Failure -> 1 incorrect.
  b. sources_valid — at least one source entry with a well-formed http(s)
     URL and a non-empty quote. Failure -> 2 incomplete.
  c. evidence_support — the normalized reference answer must be findable in
     at least one normalized quote (verify_lib.normalize_text; for numeric
     answers, the digit string must appear in the quote, thousand separators
     inside the quote allowed; the abbreviation "St." in a quote is expanded
     to "saint", so a synthetic source quoting "St. Exampleton" supports the
     reference "Saint Exampleton"). Failure -> 1 incorrect under the distinct
     check name `evidence_support`, so "answer right but evidence
     unsupporting" is distinguishable from "answer wrong".
  d. route_evidence (only with --transcript) — every cited URL must appear
     in the raw transcript text, evidencing that the cited pages were
     actually reached on the run's delivery route. Failure -> 1 incorrect
     under the check name `route_evidence`. When --transcript is omitted the
     check is recorded as skipped in the result JSON.

Exit codes follow common/verify_lib.py: 0 pass, 1 incorrect, 2 incomplete,
3 missing_artifact, 4 verifier_error (malformed/missing task file, missing
transcript file, usage errors). The result JSON is written next to the
artifacts (default DIR/verification.json). The agent's statement of
completion is never accepted; only these checks decide.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))

import verify_lib as vlib  # noqa: E402

URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)


class Parser(argparse.ArgumentParser):
    """Usage errors are verifier-side problems -> exit 4, not argparse's 2."""

    def error(self, message: str):
        self.print_usage(sys.stderr)
        vlib.die(vlib.VERIFIER_ERROR, f"usage error: {message}")


def load_task(path: str, result_path: str) -> dict:
    """Task files are ours, so absence/malformation is a verifier error (4)."""
    if not os.path.exists(path):
        vlib.die(vlib.VERIFIER_ERROR, f"task file not found: {path}",
                 result_path=result_path)
    try:
        with open(path, encoding="utf-8") as fh:
            task = json.load(fh)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        vlib.die(vlib.VERIFIER_ERROR, f"task file is not valid JSON: {path} ({exc})",
                 result_path=result_path)
    required = ("task_id", "question", "reference_answer", "provenance")
    missing = [k for k in required if k not in task]
    if missing:
        vlib.die(vlib.VERIFIER_ERROR,
                 f"task JSON malformed: missing keys {missing} in {path}",
                 result_path=result_path)
    if not all(isinstance(task[k], str) and task[k].strip()
               for k in ("task_id", "question", "reference_answer")):
        vlib.die(vlib.VERIFIER_ERROR,
                 f"task JSON malformed: task_id/question/reference_answer must "
                 f"be non-empty strings in {path}",
                 result_path=result_path)
    return task


def quote_contains_answer(reference: str, quote: str) -> bool:
    """Evidence-support containment (ours, frozen). Numeric references must
    appear as their digit string; thousand separators inside the quote are
    allowed. "St." inside a quote is expanded to "saint" so abbreviated
    place names in source text still support the unabbreviated reference
    (the GAIA questions demand unabbreviated answers)."""
    ref = vlib.normalize_text(reference)
    if not ref:
        return False
    q = vlib.normalize_text(quote)
    if vlib._try_number(ref) is not None:
        digits = re.sub(r"\D", "", ref)
        if not digits:
            return False
        q_joined = re.sub(r"(?<=\d)[.,\s](?=\d)", "", q)
        return digits in q or digits in q_joined
    q_expanded = re.sub(r"\bst\.?(?![\w.])", "saint", q)
    return ref in q or ref in q_expanded


def main() -> None:
    parser = Parser(description="GAIA-derived web-search task verifier")
    parser.add_argument("--artifacts", required=True,
                        help="agent artifact directory containing answer.json")
    parser.add_argument("--task", required=True,
                        help="path to the task JSON (gaia_tasks/<task_id>.json)")
    parser.add_argument("--transcript", default=None,
                        help="optional raw session transcript (JSONL); cited "
                             "URLs must appear in it (check route_evidence)")
    parser.add_argument("--out", default=None,
                        help="result JSON path (default: DIR/verification.json)")
    args = parser.parse_args()

    artifacts = args.artifacts
    if not os.path.isdir(artifacts):
        vlib.die(vlib.MISSING_ARTIFACT, f"artifacts directory not found: {artifacts}")
    result_path = args.out or os.path.join(artifacts, "verification.json")

    task = load_task(args.task, result_path)
    task_id = task["task_id"]

    answer_data = vlib.load_json_file(os.path.join(artifacts, "answer.json"),
                                      result_path=result_path, task_id=task_id)

    checks: list[dict] = []

    # Shape gate: required artifact parts present (failure -> 2 incomplete).
    answer = answer_data.get("answer")
    sources = answer_data.get("sources")
    shape_ok = isinstance(answer, str) and bool(answer.strip()) \
        and isinstance(sources, list)
    checks.append(vlib.check(
        "artifact_shape", shape_ok,
        "" if shape_ok else "answer.json must contain a non-empty string "
                            "'answer' and a list 'sources'"))
    if not shape_ok:
        vlib.die(vlib.INCOMPLETE, "failed check: artifact_shape",
                 result_path=result_path, task_id=task_id, checks=checks)

    valid_sources = [
        s for s in sources
        if isinstance(s, dict) and isinstance(s.get("url"), str)
        and URL_RE.match(s["url"].strip())
        and isinstance(s.get("quote"), str) and vlib.normalize_text(s["quote"])
    ]

    # (a) answer matches reference (failure -> 1 incorrect)
    a_check = vlib.check(
        "answer_matches_reference",
        vlib.answers_equal(task["reference_answer"], answer),
        f"reference={task['reference_answer']!r} candidate={answer!r}")
    checks.append(a_check)

    # (b) at least one well-formed source (failure -> 2 incomplete)
    b_check = vlib.check(
        "sources_valid", len(valid_sources) > 0,
        f"{len(valid_sources)} of {len(sources)} source entries well-formed "
        "(http(s) URL + non-empty quote)")
    checks.append(b_check)

    # (c) cited evidence supports the answer (failure -> 1 incorrect,
    #     distinct check name evidence_support)
    evidence_ok = any(quote_contains_answer(task["reference_answer"], s["quote"])
                      for s in valid_sources)
    first_quote = valid_sources[0]["quote"] if valid_sources else ""
    c_check = vlib.check(
        "evidence_support", evidence_ok,
        f"reference must appear inside a cited quote; first quote: "
        f"{first_quote[:120]!r}")
    checks.append(c_check)

    # (d) route evidence, only when a transcript is supplied
    if args.transcript is not None:
        if not os.path.exists(args.transcript):
            vlib.die(vlib.VERIFIER_ERROR,
                     f"transcript file not found: {args.transcript}",
                     result_path=result_path, task_id=task_id, checks=checks)
        with open(args.transcript, encoding="utf-8", errors="replace") as fh:
            transcript_text = fh.read()
        missing_urls = [s["url"] for s in valid_sources
                        if s["url"].strip() not in transcript_text]
        d_check = vlib.check(
            "route_evidence", not missing_urls,
            "all cited URLs appear in the raw transcript" if not missing_urls
            else f"cited URLs absent from transcript: {missing_urls}")
        checks.append(d_check)
        failing = [c for c in (a_check, b_check, c_check, d_check)
                   if not c["passed"]]
    else:
        checks.append({"check": "route_evidence", "passed": None,
                       "skipped": True,
                       "detail": "--transcript not provided; check skipped"})
        failing = [c for c in (a_check, b_check, c_check) if not c["passed"]]

    if failing:
        first = failing[0]
        code = vlib.INCOMPLETE if first is b_check else vlib.INCORRECT
        vlib.die(code, f"failed check: {first['check']}",
                 result_path=result_path, task_id=task_id, checks=checks)

    vlib.die(vlib.PASS, "all checks passed",
             result_path=result_path, task_id=task_id, checks=checks)


if __name__ == "__main__":
    main()
