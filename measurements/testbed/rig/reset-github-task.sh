#!/usr/bin/env bash
# Reset a GitHub task repo to its pinned snapshot state before a trial [ours].
#
# The official verifiers read PR lists, so a stale merged PR would fake a pass:
# reset = archive the old repo under a timestamped name and create a fresh one
# from the pinned upstream commit. With the `delete_repo` scope granted
# (`gh-github auth refresh -h github.com -s delete_repo`), set RESET_MODE=delete
# to delete instead of rename+archive.
#
# Runs against the dedicated study account: source rig/env.sh first (it exports
# GH_CONFIG_DIR for gh and git push auth), and set GITHUB_EVAL_ORG to the study
# account login (verifiers and TESTBED_GH_REPO use it). The personal login is
# never touched.
#
# Usage: reset-github-task.sh harmony|missing-semester [OWNER]
set -euo pipefail

TASK="${1:?usage: reset-github-task.sh harmony|missing-semester [OWNER]}"
OWNER="${2:-${GITHUB_EVAL_ORG:-}}"
[ -n "$OWNER" ] || { echo 'set GITHUB_EVAL_ORG (study account login) or pass OWNER' >&2; exit 2; }
MODE="${RESET_MODE:-archive}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

case "$TASK" in
  harmony)
    UPSTREAM=https://github.com/mcpmark-source/harmony.git
    PIN=f348e7689f5f0599b7cfef7de6d6a597a57615c7
    BRANCH=main ;;
  missing-semester)
    UPSTREAM=https://github.com/mcpmark-source/missing-semester.git
    PIN=05c436fbdf0d3d90cfaa86f22bd37ad9bd1608fa
    BRANCH=master ;;
  *) echo "unknown task: $TASK" >&2; exit 1 ;;
esac

if gh repo view "$OWNER/$TASK" >/dev/null 2>&1; then
  if [ "$MODE" = "delete" ]; then
    gh repo delete "$OWNER/$TASK" --yes
  else
    gh repo rename "$TASK-retired-$STAMP" --repo "$OWNER/$TASK" --yes
    gh repo archive "$OWNER/$TASK-retired-$STAMP" --yes || true
  fi
fi

gh repo create "$OWNER/$TASK" --private \
  --description "Study task state ($TASK @ $PIN); disposable, reset per trial"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git -c advice.detachedHead=false clone -q "$UPSTREAM" "$TMP/src"
git -C "$TMP/src" checkout -q "$PIN"
git -C "$TMP/src" remote add fresh "https://github.com/$OWNER/$TASK.git"
git -C "$TMP/src" push -q fresh "HEAD:refs/heads/$BRANCH"

echo "reset ok: $OWNER/$TASK @ $PIN ($BRANCH), PRs: $(gh pr list -R "$OWNER/$TASK" --state all --json number -q length)"
