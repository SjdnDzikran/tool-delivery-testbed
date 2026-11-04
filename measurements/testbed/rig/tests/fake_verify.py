#!/usr/bin/env python3
"""Fake verifier for offline runner tests [ours].

Contract-compatible with testbed verifiers: exit code from FAKE_VERIFIER_EXIT
(default 0 = pass); writes a machine-readable verification.json next to the
--artifacts directory argument.
"""
import argparse
import json
import os
import sys

VERDICTS = {0: "pass", 1: "incorrect", 2: "incomplete", 3: "missing_artifact",
            4: "verifier_error"}

p = argparse.ArgumentParser()
p.add_argument("--artifacts")
args = p.parse_args()
code = int(os.environ.get("FAKE_VERIFIER_EXIT", "0"))
if args.artifacts:
    with open(os.path.join(args.artifacts, "verification.json"), "w") as fh:
        json.dump({"verdict": VERDICTS.get(code, "verifier_error"),
                   "exit_code": code}, fh, indent=2)
print(f"[fake verifier] exit {code}")
sys.exit(code)
