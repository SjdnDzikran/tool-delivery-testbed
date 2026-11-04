#!/usr/bin/env python3
"""Verifier for the database capability smoke [ours].

Checks both the artifact (reported row count) and the live fixture state
(the smoke_items table with exactly the two required rows).
"""
from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import VERIFIER_ERROR, check, finish, parse_artifacts  # noqa: E402

TASK_ID = "cap_db"


def db_count(dsn: str | None) -> int:
    if not dsn:
        print("TESTBED_PG_DSN not set; verifier cannot check live state",
              file=sys.stderr)
        raise SystemExit(VERIFIER_ERROR)
    proc = subprocess.run(
        ["psql", dsn, "-tAc",
         "SELECT count(*) FROM smoke_items WHERE (id, label) IN ((1,'alpha'),(2,'beta'))"],
        capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        print(f"psql failed: {proc.stderr.strip()[:200]}", file=sys.stderr)
        raise SystemExit(VERIFIER_ERROR)
    return int(proc.stdout.strip())


def main() -> int:
    artifacts = parse_artifacts(sys.argv[1:])
    checks = []
    count_path = os.path.join(artifacts, "db_rows.txt")
    if not os.path.isfile(count_path):
        checks.append(check("db_rows.txt exists", False, "missing"))
        return finish(TASK_ID, artifacts, checks)
    checks.append(check("db_rows.txt exists", True))
    raw = open(count_path, encoding="utf-8", errors="replace").read().strip()
    checks.append(check("reported count is 2", raw == "2", f"got {raw[:20]!r}"))
    try:
        live = db_count(os.environ.get("TESTBED_PG_DSN"))
    except SystemExit as exc:
        raise exc
    checks.append(check("smoke_items holds exactly the two required rows",
                        live == 2, f"matching rows: {live}"))
    return finish(TASK_ID, artifacts, checks)


if __name__ == "__main__":
    sys.exit(main())
