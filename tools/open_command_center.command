#!/bin/zsh
set -euo pipefail

URL="${NEXUX_COMMAND_CENTER_URL:-http://127.0.0.1:8812/m/command-center/}"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE="$HOME/Library/Application Support/NexUX Command Center"

if [[ ! -x "$CHROME" ]]; then
  print -u2 "Google Chrome no está instalado en /Applications."
  exit 1
fi

mkdir -p "$PROFILE"

nohup "$CHROME" \
  --app="$URL" \
  --kiosk \
  --user-data-dir="$PROFILE" \
  --no-first-run \
  --no-default-browser-check \
  --disable-session-crashed-bubble \
  >/dev/null 2>&1 &
