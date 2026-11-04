#!/bin/sh
# Stop the loopback fixture app started by serve-fixture.sh [ours].
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
RIG_RUNTIME=$(CDPATH= cd -- "$HERE/../.." && pwd)/runtime
PIDFILE="$RIG_RUNTIME/browser-fixture.pid"
if [ -f "$PIDFILE" ]; then
  kill "$(cat "$PIDFILE")" 2>/dev/null || true
  rm -f "$PIDFILE"
  echo "fixture app: stopped"
else
  echo "fixture app: not running (no pidfile)"
fi
