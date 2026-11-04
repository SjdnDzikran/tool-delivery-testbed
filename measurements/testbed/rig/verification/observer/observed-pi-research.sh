#!/usr/bin/env bash
# Verification-only harness wrapper [ours].
#
# Executes the pinned research Pi (pi-research 1.0.4) with the read-only
# request observer extension injected as an explicit `-e` path immediately
# before the `--` instruction separator. Documented behavior (pi --help):
# `--no-extensions  Disable extension discovery and built-in extensions
#                    (explicit -e paths still work)` — so discovery stays
# off exactly as in campaign argv; only the observer extension loads.
# Requires a `--` argument (the runner always emits one); otherwise the
# wrapper refuses to run so the flag can never be mistaken for a message.
#
# PI_OBSERVER_DIR / PI_OBSERVER_RAW_DIR are BASE dirs passed through the
# manifest env allowlist. This wrapper appends a per-invocation tag derived
# from PI_CODING_AGENT_DIR (.../trials/<trial_id>/attempt-NNN/agent-dir),
# so payloads from concurrent or sequential trials never collide.
set -euo pipefail
HARNESS="${PI_VERIFY_HARNESS:-$HOME/.local/bin/pi-research}"
OBS="$(cd "$(dirname "$0")" && pwd)/pi-request-observer.ts"

if [ -n "${PI_CODING_AGENT_DIR:-}" ]; then
  # agent-dir -> attempt-NNN -> <trial_id>
  TAG="$(basename "$(dirname "$(dirname "${PI_CODING_AGENT_DIR}")")")"
else
  TAG="adhoc-$$"
fi
if [ -n "${PI_OBSERVER_DIR:-}" ]; then
  export PI_OBSERVER_DIR="${PI_OBSERVER_DIR%/}/${TAG}"
  mkdir -p "$PI_OBSERVER_DIR"
fi
if [ -n "${PI_OBSERVER_RAW_DIR:-}" ]; then
  export PI_OBSERVER_RAW_DIR="${PI_OBSERVER_RAW_DIR%/}/${TAG}"
  mkdir -p "$PI_OBSERVER_RAW_DIR"
fi

new=()
found_dd=0
for a in "$@"; do
  if [ "$a" = "--" ]; then
    new+=("-e" "$OBS")
    found_dd=1
  fi
  new+=("$a")
done
if [ "$found_dd" -ne 1 ]; then
  echo "observed-pi-research.sh: no '--' separator in argv; refusing (would corrupt argv)" >&2
  exit 64
fi
exec "$HARNESS" "${new[@]}"
