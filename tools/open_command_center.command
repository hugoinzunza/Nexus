#!/bin/zsh
set -euo pipefail

URL="${NEXUX_COMMAND_CENTER_URL:-http://127.0.0.1:8812/m/command-center/}"

open -na "Google Chrome" --args \
  --app="$URL" \
  --start-fullscreen \
  --disable-session-crashed-bubble
