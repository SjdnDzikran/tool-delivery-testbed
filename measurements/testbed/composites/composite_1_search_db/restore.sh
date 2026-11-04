#!/usr/bin/env bash
# Restore the versioned initial state for composite_1_search_db [ours].
#
# Idempotent: drops/recreates public.facts and reseeds it.
# Requires TESTBED_PG_DSN; refuses to run without it (no default database).
# Override the psql client with PSQL_CMD if the rig wraps it.
#
# Live-DB execution is environment-pending: this dev environment has no
# reachable PostgreSQL server, so this script has not been run end-to-end.
set -euo pipefail

: "${TESTBED_PG_DSN:?refusing to run: TESTBED_PG_DSN is not set}"
PSQL_CMD="${PSQL_CMD:-psql}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"$PSQL_CMD" -X -v ON_ERROR_STOP=1 "$TESTBED_PG_DSN" \
    -f "$DIR/fixtures/schema.sql" \
    -f "$DIR/fixtures/seed.sql"

echo "restore.sh: composite_1_search_db initial state restored."
