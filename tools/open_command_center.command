#!/bin/zsh
set -euo pipefail

URL="${NEXUX_COMMAND_CENTER_URL:-http://127.0.0.1:8812/m/command-center/}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/.build/NexUX Command Center.app"

"$ROOT/tools/build_command_center_shell.command" >/dev/null
open -na "$APP" --args "$URL"
