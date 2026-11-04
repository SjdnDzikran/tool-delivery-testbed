#!/usr/bin/env python3
"""Verifier for the GitHub capability smoke [ours]."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import check, finish, load_json_file, parse_artifacts  # noqa: E402

TASK_ID = "cap_gh"
EXPECTED_REPO = os.environ.get("TESTBED_GH_REPO")


def main() -> int:
    artifacts = parse_artifacts(sys.argv[1:])
    checks = []
    result = load_json_file(os.path.join(artifacts, "repo.json"),
                            os.path.join(artifacts, "verification.json"))
    ok = isinstance(result, dict)
    checks.append(check("repo.json is an object", ok, f"got {type(result).__name__}"))
    if not ok:
        return finish(TASK_ID, artifacts, checks)
    keys = set(result)
    checks.append(check("exact keys {nameWithOwner,description}",
                        keys == {"nameWithOwner", "description"}, f"got {sorted(keys)}"))
    repo = result.get("nameWithOwner")
    checks.append(check("nameWithOwner matches the configured task repository",
                        EXPECTED_REPO is not None and repo == EXPECTED_REPO, repr(repo)))
    desc = result.get("description")
    checks.append(check("description is a string or null",
                        isinstance(desc, str) or desc is None,
                        type(desc).__name__))
    return finish(TASK_ID, artifacts, checks)


if __name__ == "__main__":
    sys.exit(main())
