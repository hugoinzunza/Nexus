#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="$ROOT/agents/macos/CommandCenterShell/main.swift"
PLIST="$ROOT/agents/macos/CommandCenterShell/Info.plist"
APP="$ROOT/.build/NexUX Command Center.app"
MACOS="$APP/Contents/MacOS"

mkdir -p "$MACOS"
cp "$PLIST" "$APP/Contents/Info.plist"
xcrun swiftc "$SOURCE" \
  -O \
  -framework AppKit \
  -framework EventKit \
  -framework WebKit \
  -o "$MACOS/NexUXCommandCenter"

print "$APP"
