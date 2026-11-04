#!/usr/bin/env python3
"""Stub psql client for composite_2 validation (no server, no network).

Dispatches on the SQL text passed with -c; the canned response is chosen by
the STUB_SALES_MODE environment variable:

  correct      'Aurora Lamp|620'  - the true aggregate of fixtures/seed.sql
  alt_product  'Birch Desk|590'   - a different, self-consistent aggregate,
                 used to prove the verifier computes its expectation instead
                 of holding a frozen answer
  error        connection-style failure on stderr, exit 2

Output shape mirrors psql -At (tuples-only, unaligned): 'product|total'.
"""
import os
import sys


def main() -> None:
    argv = sys.argv[1:]
    sql = argv[argv.index("-c") + 1] if "-c" in argv else ""
    if "SUM(units)" not in sql or "product_sales" not in sql:
        print(f"stub_psql: unrecognised SQL: {sql[:120]!r}", file=sys.stderr)
        sys.exit(3)
    mode = os.environ.get("STUB_SALES_MODE", "correct")
    if mode == "error":
        print("psql: error: could not connect to server: Connection refused",
              file=sys.stderr)
        sys.exit(2)
    if mode == "alt_product":
        print("Birch Desk|590")
    else:
        print("Aurora Lamp|620")
    sys.exit(0)


if __name__ == "__main__":
    main()
