#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.hugo.nexux-shadow-exit"
DOMAIN="gui/$(id -u)"
SOURCE="$ROOT/deploy/$LABEL.plist"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$ROOT/logs" "$HOME/Library/LaunchAgents"
changed=0
if ! cmp -s "$SOURCE" "$TARGET" 2>/dev/null; then
    cp "$SOURCE" "$TARGET"
    changed=1
fi
if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
    if (( changed )); then
        launchctl bootout "$DOMAIN/$LABEL"
        launchctl bootstrap "$DOMAIN" "$TARGET"
    else
        launchctl kickstart -k "$DOMAIN/$LABEL"
    fi
else
    launchctl enable "$DOMAIN/$LABEL"
    launchctl bootstrap "$DOMAIN" "$TARGET"
fi

print "Shadow observer activo: $LABEL"
