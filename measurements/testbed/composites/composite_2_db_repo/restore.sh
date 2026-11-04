#!/usr/bin/env bash
# Restore the versioned initial state for composite_2_db_repo [ours].
#
# Two parts, both idempotent:
#   1. Database: drops/recreates public.product_sales and reseeds it.
#      Requires TESTBED_PG_DSN; refuses to run without it (no default
#      database). Override the psql client with PSQL_CMD if the rig wraps it.
#   2. Repository: the published file TOP_SELLER.md must be ABSENT at the
#      start of a run. When TESTBED_GH_REPO and GITHUB_TOKEN are set, it is
#      deleted through the GitHub REST API (a deletion commit on the default
#      branch). Otherwise the rig must remove it manually.
#
# Live execution (PostgreSQL + GitHub REST) is environment-pending: this dev
# environment has neither a reachable server nor network access, so this
# script has not been run end-to-end here.
set -euo pipefail

: "${TESTBED_PG_DSN:?refusing to run: TESTBED_PG_DSN is not set}"
PSQL_CMD="${PSQL_CMD:-psql}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- 1. database state -----------------------------------------------------
"$PSQL_CMD" -X -v ON_ERROR_STOP=1 "$TESTBED_PG_DSN" \
    -f "$DIR/fixtures/schema.sql" \
    -f "$DIR/fixtures/seed.sql"

# --- 2. repository state ---------------------------------------------------
if [[ -n "${TESTBED_GH_REPO:-}" && -n "${GITHUB_TOKEN:-}" ]]; then
    python3 - "$TESTBED_GH_REPO" <<'PY'
import json
import os
import sys
import urllib.error
import urllib.request

repo = sys.argv[1]
token = os.environ["GITHUB_TOKEN"]
path = "TOP_SELLER.md"
url = f"https://api.github.com/repos/{repo}/contents/{path}"
headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "testbed-restore",
}

# Locate the file to obtain its SHA (required by the delete endpoint).
req = urllib.request.Request(url, headers=headers)
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        sha = json.load(resp)["sha"]
except urllib.error.HTTPError as exc:
    if exc.code == 404:
        print("restore.sh: TOP_SELLER.md already absent on the default branch")
        sys.exit(0)
    print(f"restore.sh: GitHub API error {exc.code} while locating TOP_SELLER.md",
          file=sys.stderr)
    sys.exit(1)

body = json.dumps({"message": "testbed: reset initial state", "sha": sha}).encode()
req = urllib.request.Request(url, data=body, headers=headers, method="DELETE")
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()
except urllib.error.HTTPError as exc:
    print(f"restore.sh: GitHub API error {exc.code} while deleting TOP_SELLER.md",
          file=sys.stderr)
    sys.exit(1)
print(f"restore.sh: deleted TOP_SELLER.md from {repo}")
PY
else
    echo "restore.sh: TESTBED_GH_REPO/GITHUB_TOKEN not set - remove" \
         "TOP_SELLER.md from the default branch manually before the run."
fi

echo "restore.sh: composite_2_db_repo initial state restored."
