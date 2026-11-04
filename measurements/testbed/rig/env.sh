#!/bin/sh
# Local executable paths for the optional testbed runtime.
# Credentials are never read automatically; export them explicitly in a private shell.
#
#   . measurements/testbed/rig/env.sh
_s=${BASH_SOURCE:-$0}
RIG_DIR=$(CDPATH= cd -- "$(dirname -- "$_s")" && pwd)
case ":$PATH:" in
  *":$RIG_DIR/runtime/bin:"*) ;;
  *) PATH="$RIG_DIR/runtime/bin:$PATH"; export PATH ;;
esac

# Both browser routes use this exact local executable when installed.
PLAYWRIGHT_MCP_EXECUTABLE_PATH="$RIG_DIR/runtime/chrome/opt/google/chrome/chrome"
export PLAYWRIGHT_MCP_EXECUTABLE_PATH
PLAYWRIGHT_BROWSERS_PATH=0
export PLAYWRIGHT_BROWSERS_PATH

# Keep GitHub CLI credentials separate from the user's default gh profile.
# Authenticate a disposable account explicitly in this config directory.
GH_CONFIG_DIR="${GH_STUDY_CONFIG_DIR:-$HOME/.config/gh-study}"
export GH_CONFIG_DIR
