"""Shared utilities for testbed verifiers (stdlib only, Python 3.10+).

Exit-code contract for every verifier in this testbed:

  0  PASS               all required checks passed
  1  INCORRECT          artifacts exist but contents are wrong
  2  INCOMPLETE         artifacts exist but required parts are missing
  3  MISSING_ARTIFACT   a required file/state does not exist
  4  VERIFIER_ERROR     the verifier itself failed (environment or bug)

Every verifier writes a machine-readable result JSON recording each check,
so a wrong answer can be distinguished from a verification error. Reference
answers, expected outputs, and verifier code stay outside agent-accessible
task resources. These checks are ours [ours] and are frozen before the
campaign; they do not accept the agent's statement of completion.
"""
from __future__ import annotations

import json
import math
import re
import sys
import unicodedata

PASS, INCORRECT, INCOMPLETE, MISSING_ARTIFACT, VERIFIER_ERROR = 0, 1, 2, 3, 4

VERDICTS = {0: "pass", 1: "incorrect", 2: "incomplete", 3: "missing_artifact",
            4: "verifier_error"}


def write_result(path: str, task_id: str, code: int, checks: list[dict],
                 diagnostics: str = "") -> None:
    """Write the machine-readable verifier outcome. Checks are ordered."""
    out = {"task_id": task_id, "verdict": VERDICTS[code], "exit_code": code,
           "checks": checks, "diagnostics": diagnostics}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def die(code: int, message: str, result_path: str | None = None,
        task_id: str = "?", checks: list[dict] | None = None,
        diagnostics: str = "") -> None:
    """Record (optionally) and report a terminal verifier outcome."""
    if result_path:
        write_result(result_path, task_id, code, checks or [], diagnostics or message)
    print(f"[{VERDICTS[code].upper()}] {message}")
    sys.exit(code)


def load_json_file(path: str, result_path: str | None = None,
                   task_id: str = "?") -> dict:
    """Load a JSON artifact, mapping absence/invalidity to contract codes."""
    import os
    if not os.path.exists(path):
        die(MISSING_ARTIFACT, f"required artifact not found: {path}",
            result_path, task_id)
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        die(INCOMPLETE, f"artifact is not valid JSON: {path} ({exc})",
            result_path, task_id)


_NUM_RE = re.compile(r"^-?\d+(?:[.,]\d+)?$")


def _try_number(text: str):
    """Parse a bare number allowing ',' or '.' as decimal separator."""
    t = text.strip().replace(" ", "")
    if not _NUM_RE.match(t):
        return None
    try:
        return float(t.replace(",", "."))
    except ValueError:
        return None


def normalize_text(value: str) -> str:
    """Canonical form for free-text answer comparison.

    NFKC, case-folded, punctuation stripped (numbers keep internal separators),
    surrounding quotes removed, whitespace collapsed, leading articles dropped.
    """
    s = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    s = s.strip("\"'“”‘’").strip()
    s = re.sub(r"\s+", " ", s)
    out, kept = [], False
    for ch in s:
        if ch.isalnum() or ch in ".,%€$£-":
            out.append(ch)
            kept = True
        elif ch == " " and kept and out and out[-1] != " ":
            out.append(ch)
    s = "".join(out).strip(" .,")
    for article in ("the ", "a ", "an "):
        if s.startswith(article):
            s = s[len(article):]
            break
    return s


def answers_equal(reference: str, candidate: str) -> bool:
    """Layered equality for short reference answers (ours, frozen).

    1. exact string equality;
    2. equality after normalize_text;
    3. numeric equality when both sides are bare numbers (tolerance 1e-9),
       so '1815', '1,815', and '1815.0' match.
    """
    if str(reference) == str(candidate):
        return True
    a, b = normalize_text(reference), normalize_text(candidate)
    if a == b and a != "":
        return True
    na, nb = _try_number(a), _try_number(b)
    if na is not None and nb is not None:
        return math.isclose(na, nb, rel_tol=1e-9, abs_tol=1e-9)
    return False


def deep_equal(expected, got, path: str = "$", tol: float = 1e-9) -> tuple[bool, str]:
    """Order-sensitive deep equality for JSON values; floats use tolerance."""
    if isinstance(expected, dict) and isinstance(got, dict):
        for key in sorted(set(expected) | set(got)):
            if key not in expected:
                return False, f"{path}.{key}: unexpected key"
            if key not in got:
                return False, f"{path}.{key}: missing key"
            ok, why = deep_equal(expected[key], got[key], f"{path}.{key}", tol)
            if not ok:
                return ok, why
        return True, ""
    if isinstance(expected, list) and isinstance(got, list):
        if len(expected) != len(got):
            return False, f"{path}: length {len(got)} != expected {len(expected)}"
        for i, (e, g) in enumerate(zip(expected, got)):
            ok, why = deep_equal(e, g, f"{path}[{i}]", tol)
            if not ok:
                return ok, why
        return True, ""
    if isinstance(expected, bool) or isinstance(got, bool):
        return expected is got, ("" if expected is got else f"{path}: {got!r} != {expected!r}")
    if isinstance(expected, (int, float)) and isinstance(got, (int, float)):
        return math.isclose(expected, got, rel_tol=tol, abs_tol=tol), (
            "" if math.isclose(expected, got, rel_tol=tol, abs_tol=tol)
            else f"{path}: {got} != expected {expected}")
    return expected == got, ("" if expected == got else f"{path}: {got!r} != expected {expected!r}")


def check(name: str, passed: bool, detail: str = "") -> dict:
    """Build one entry of the checks list."""
    return {"check": name, "passed": bool(passed), "detail": detail}
