#!/bin/sh
# Start the disposable loopback fixture app for browser-capability smokes
# [ours]. Idempotent: kills a previous instance recorded in the pidfile
# first. Binds 127.0.0.1:5580 only; serves ONLY fixture-app/. Stop with
# stop-fixture.sh (or the runner's reset hook).
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
RIG_RUNTIME=$(CDPATH= cd -- "$HERE/../.." && pwd)/runtime
PIDFILE="$RIG_RUNTIME/browser-fixture.pid"
PORT=5580

if [ -f "$PIDFILE" ]; then
  kill "$(cat "$PIDFILE")" 2>/dev/null || true
  rm -f "$PIDFILE"
fi
cd "$HERE/fixture-app"
nohup python3 -m http.server "$PORT" --bind 127.0.0.1 >/dev/null 2>&1 &
echo $! > "$PIDFILE"
i=0
while [ "$i" -lt 15 ]; do
  if python3 -c "import socket,sys; s=socket.create_connection(('127.0.0.1',$PORT),1); s.close()" 2>/dev/null; then
    echo "fixture app: http://127.0.0.1:$PORT/ (pid $(cat "$PIDFILE"))"
    exit 0
  fi
  i=$((i + 1)); sleep 1
done
echo "fixture app: did not become ready on port $PORT" >&2
exit 1
