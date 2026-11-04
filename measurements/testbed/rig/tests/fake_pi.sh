#!/usr/bin/env bash
# Fake pinned-Pi executable for offline tests [ours].
# Emits valid Pi 1.0.4 json-mode event shapes WITHOUT any model or network
# access. Dumps argv/env/cwd for flag assertions. Behaviour via env:
#   FAKE_PI_DUMP   dir for env.txt/argv.txt/cwd.txt (required)
#   FAKE_SCENARIO  ok | assistant_error | quota | quota_then_ok | hang | exit7
#   FAKE_STATE     counter file for quota_then_ok
#   FAKE_ARTIFACT  file to write as the task artifact (ok scenarios)
#   FAKE_SLEEP     seconds to sleep before events (default 0)
set -u
# Version probe (doctor): respond without needing a dump dir.
for a in "$@"; do
  if [ "$a" = "--version" ]; then echo "0.0.0-fake"; exit 0; fi
done
DUMP="${FAKE_PI_DUMP:?FAKE_PI_DUMP required}"
mkdir -p "$DUMP"
printf '%s\n' "$@" > "$DUMP/argv.txt"
env | LC_ALL=C sort > "$DUMP/env.txt"
pwd > "$DUMP/cwd.txt"

SC="${FAKE_SCENARIO:-ok}"
if [ "$SC" = "quota_then_ok" ]; then
  N="$(cat "${FAKE_STATE:?}" 2>/dev/null || echo 0)"
  N=$((N + 1)); printf '%s' "$N" > "$FAKE_STATE"
  if [ "$N" -eq 1 ]; then SC="quota"; else SC="ok"; fi
fi

sleep "${FAKE_SLEEP:-0}"

emit_usage() {  # one fake usage object
  printf '"usage":{"input":10,"output":5,"cacheRead":0,"cacheWrite":0,"totalTokens":15,"cost":{"input":0,"output":0,"cacheRead":0,"cacheWrite":0,"total":0}}'
}

ART="${FAKE_ARTIFACT:-}"
ART="${ART/__CWD__/$PWD}"

case "$SC" in
  hang)
    printf '{"type":"session","version":3,"id":"fake-hang","timestamp":"2026-01-01T00:00:00.000Z","cwd":"%s"}\n' "$PWD"
    sleep 300
    exit 0 ;;
  exit7)
    printf '{"type":"session","version":3,"id":"fake-exit7","timestamp":"2026-01-01T00:00:00.000Z","cwd":"%s"}\n' "$PWD"
    echo "boom" >&2
    exit 7 ;;
esac

printf '{"type":"session","version":3,"id":"fake-%s","timestamp":"2026-01-01T00:00:00.000Z","cwd":"%s"}\n' "$SC" "$PWD"
printf '{"type":"agent_start"}\n'
printf '{"type":"turn_start"}\n'
printf '{"type":"message_end","message":{"role":"user","content":"fake prompt","timestamp":1}}\n'
case "$SC" in
  assistant_error)
    printf '{"type":"message_end","message":{"role":"assistant","content":[],"provider":"fake","model":"fake",%s,"stopReason":"error","errorMessage":"provider exploded","timestamp":2}}\n' "$(emit_usage)" ;;
  quota)
    printf '{"type":"message_end","message":{"role":"assistant","content":[],"provider":"fake","model":"fake",%s,"stopReason":"error","rawStopReason":"429","errorMessage":"HTTP 429 insufficient_quota: rate limit exceeded","timestamp":2}}\n' "$(emit_usage)" ;;
  ok)
    if [ -n "$ART" ]; then
      printf '{"ok": true}\n' > "$ART"
    fi
    printf '{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"done"}],"provider":"fake","model":"fake",%s,"stopReason":"stop","timestamp":2}}\n' "$(emit_usage)" ;;
esac
printf '{"type":"turn_end","message":{"role":"assistant"},"toolResults":[]}\n'
printf '{"type":"agent_end","messages":[],"willRetry":false}\n'
printf '{"type":"agent_settled"}\n'
exit 0
