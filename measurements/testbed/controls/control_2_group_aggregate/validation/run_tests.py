#!/usr/bin/env python3
"""Validation fixtures for the control_2_group_aggregate verifier [ours].

Builds artifact cases at runtime in a temporary directory and asserts the
exit-code contract of common/verify_lib.py:

  known-correct result                 -> 0 pass
  altered total_salary value           -> 1 incorrect
  avg_salary under the wrong rounding
  convention (half-to-even .12)        -> 1 incorrect
  renamed inner key                    -> 2 incomplete
  region keys not sorted alphabetically -> 2 incomplete
  array where object expected          -> 2 incomplete
  invalid JSON                         -> 2 incomplete
  empty artifacts directory            -> 3 missing_artifact
  nonexistent artifacts path           -> 3 missing_artifact
  expected/result.json missing (copy)  -> 4 verifier_error

Prints PASS/FAIL per case and exits nonzero if any case fails.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONTROL = HERE.parent
TESTBED = CONTROL.parent.parent
VERIFY = CONTROL / "verify.py"
VERIFY_LIB = TESTBED / "common" / "verify_lib.py"
EXPECTED_PATH = CONTROL / "expected" / "result.json"

VERDICTS = {0: "pass", 1: "incorrect", 2: "incomplete",
            3: "missing_artifact", 4: "verifier_error"}


def _load(path: Path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def _altered_total(case_dir: Path) -> None:
    data = _load(EXPECTED_PATH)
    data["North"]["total_salary"] = data["North"]["total_salary"] + 1
    _write_json(case_dir / "result.json", data)


def _avg_half_even_convention(case_dir: Path) -> None:
    # 749945 / 8 = 93743.125: correct half-away-from-zero is .13; the
    # half-to-even result .12 must fail under the pinned convention.
    data = _load(EXPECTED_PATH)
    data["North"]["avg_salary"] = 93743.12
    _write_json(case_dir / "result.json", data)


def _renamed_key(case_dir: Path) -> None:
    data = _load(EXPECTED_PATH)
    data["North"]["sum_salary"] = data["North"].pop("total_salary")
    _write_json(case_dir / "result.json", data)


def _unsorted_regions(case_dir: Path) -> None:
    data = _load(EXPECTED_PATH)
    _write_json(case_dir / "result.json", dict(reversed(list(data.items()))))


def _wrong_shape(case_dir: Path) -> None:
    _write_json(case_dir / "result.json", [data for data in [_load(EXPECTED_PATH)]])


def _invalid_json(case_dir: Path) -> None:
    (case_dir / "result.json").write_text("{not json", encoding="utf-8")


def _run_verifier(verify_path: Path, artifacts: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(verify_path), "--artifacts", str(artifacts)],
        capture_output=True, text=True)


def main() -> int:
    cases: list[tuple[str, object, int]] = [
        ("known-correct result passes",
         lambda d: shutil.copyfile(EXPECTED_PATH, d / "result.json"), 0),
        ("one altered total_salary value", _altered_total, 1),
        ("avg_salary with half-to-even .12 (wrong convention)", _avg_half_even_convention, 1),
        ("renamed inner key", _renamed_key, 2),
        ("region keys not sorted alphabetically", _unsorted_regions, 2),
        ("array where object expected", _wrong_shape, 2),
        ("invalid JSON", _invalid_json, 2),
        ("empty artifacts directory", lambda d: None, 3),
        ("nonexistent artifacts path", None, 3),
    ]

    failures: list[str] = []
    total = len(cases) + 1  # + the verifier_error case below
    with tempfile.TemporaryDirectory(prefix="control_2_validation_") as tmp:
        root = Path(tmp)
        for index, (name, builder, want) in enumerate(cases):
            case_dir = root / f"case_{index:02d}"
            if builder is not None:
                case_dir.mkdir()
                builder(case_dir)
            proc = _run_verifier(VERIFY, case_dir)
            notes = []
            if proc.returncode != want:
                notes.append(f"expected exit {want}, got {proc.returncode}")
                if proc.stdout.strip():
                    notes.append(f"stdout: {proc.stdout.strip()}")
                if proc.stderr.strip():
                    notes.append(f"stderr: {proc.stderr.strip()}")
            report = case_dir / "verification.json"
            if report.exists():
                verdict = _load(report).get("verdict")
                if verdict != VERDICTS[want]:
                    notes.append(f"expected verdict {VERDICTS[want]!r}, got {verdict!r}")
            if notes:
                failures.append(name)
                print(f"[FAIL] {name}: " + "; ".join(notes))
            else:
                print(f"[PASS] {name} -> exit {proc.returncode} ({VERDICTS[want]})")

        # verifier_error: a stripped copy of the control tree without expected/.
        # The copy sits at <root>/controls/broken_control so the verifier's
        # ../../common import resolves to <root>/common (mirroring the real tree).
        broken = root / "controls" / "broken_control"
        (broken).mkdir(parents=True)
        (root / "common").mkdir()
        shutil.copyfile(VERIFY, broken / "verify.py")
        shutil.copyfile(VERIFY_LIB, root / "common" / "verify_lib.py")
        broken_artifacts = root / "broken_artifacts"
        broken_artifacts.mkdir()
        shutil.copyfile(EXPECTED_PATH, broken_artifacts / "result.json")
        name = "expected/result.json missing -> verifier error"
        proc = _run_verifier(broken / "verify.py", broken_artifacts)
        if proc.returncode == 4:
            print(f"[PASS] {name} -> exit 4 ({VERDICTS[4]})")
        else:
            failures.append(name)
            print(f"[FAIL] {name}: expected exit 4, got {proc.returncode}")

    print(f"{total - len(failures)}/{total} validation cases passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
