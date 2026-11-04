#!/usr/bin/env bash
# Thin wrapper for the manifest-driven runner [ours].
#
# The 2026-10-27 draft internals (instance-dir + catalog + --no-session
# composition) were flawed and are replaced by runner.py:
#   - --no-extensions disabled built-in MCP unless explicitly reloaded with
#     -e builtin:mcp (deferred exposure also needs -e builtin:tool-search);
#   - the CLI arm did not actually disable MCP nor load selected skills;
#   - --no-session conflicted with persistent sessions for audit;
#   - model default provider IDs were not explicit.
#
# Usage (see ../README.md):
#   runner.py validate|plan|doctor|run|resume|status|trial  MANIFEST|FLAGS
#
# Legacy positional interface (INSTANCE INSTRUCTION WORKSPACE CATALOG
# [DEADLINE]) is no longer accepted: use `runner.py trial ...` for one
# ad-hoc smoke trial or a manifest for a campaign. The reset script
# (reset-github-task.sh) is unchanged and is invoked by task reset commands,
# never by this wrapper.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "$#" -eq 0 ]; then
  exec python3 "$DIR/runner.py" --help
fi
echo "run-trial.sh is a thin wrapper; delegating to runner.py" >&2
exec python3 "$DIR/runner.py" "$@"
