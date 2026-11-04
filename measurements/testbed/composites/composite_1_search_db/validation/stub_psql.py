#!/usr/bin/env python3
"""Stub psql client for composite_1 validation (no server, no network).

Dispatches on the SQL text passed with -c; the canned response is chosen by
the STUB_FACTS_MODE environment variable:

  correct      one row with the correct value and source URL (default)
  no_row       zero rows (query succeeds)
  wrong_value  one row whose value does not match the evidence
  wrong_url    one row whose source_url does not match the evidence
  duplicate    two identical rows
  error        connection-style failure on stderr, exit 2

The canned row mirrors fixtures/seed.sql expectations and the task's
frozen reference; see verify.py for the row_to_json query shape.
"""
import json
import os
import sys


def main() -> None:
    argv = sys.argv[1:]
    sql = argv[argv.index("-c") + 1] if "-c" in argv else ""
    if "row_to_json" not in sql or "facts" not in sql:
        print(f"stub_psql: unrecognised SQL: {sql[:120]!r}", file=sys.stderr)
        sys.exit(3)
    mode = os.environ.get("STUB_FACTS_MODE", "correct")
    if mode == "error":
        print("psql: error: could not connect to server: Connection refused",
              file=sys.stderr)
        sys.exit(2)
    if mode == "no_row":
        sys.exit(0)
    row = {
        "label": "birth_year_grace_hopper",
        "value": "1906",
        "source_url": "https://en.wikipedia.org/wiki/Grace_Hopper",
    }
    if mode == "wrong_value":
        row["value"] = "1907"
    elif mode == "wrong_url":
        row["source_url"] = "https://example.org/hopper-biography"
    line = json.dumps(row)
    print(line)
    if mode == "duplicate":
        print(line)
    sys.exit(0)


if __name__ == "__main__":
    main()
