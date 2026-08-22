#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PACKAGE="$ROOT/agents/macos/NexusAgent"
APP="$HOME/Applications/NexUX Media Agent.app"
DESTINATION="$APP/Contents/MacOS"
PLIST="$APP/Contents/Info.plist"

swift build --package-path "$PACKAGE" -c release --product nexus-agent
mkdir -p "$DESTINATION"
install -m 0755 "$PACKAGE/.build/release/nexus-agent" "$DESTINATION/nexus-agent"
/usr/bin/plutil -create xml1 "$PLIST"
/usr/bin/plutil -insert CFBundleExecutable -string nexus-agent "$PLIST"
/usr/bin/plutil -insert CFBundleIdentifier -string cl.nexux.media-agent.local "$PLIST"
/usr/bin/plutil -insert CFBundleName -string "NexUX Media Agent" "$PLIST"
/usr/bin/plutil -insert CFBundlePackageType -string APPL "$PLIST"
/usr/bin/plutil -insert CFBundleShortVersionString -string 1.0 "$PLIST"
/usr/bin/plutil -insert CFBundleVersion -string 1 "$PLIST"
/usr/bin/plutil -insert LSMinimumSystemVersion -string 13.0 "$PLIST"
/usr/bin/plutil -insert LSUIElement -bool true "$PLIST"
codesign --force --deep --sign - "$APP" >/dev/null

print "$DESTINATION/nexus-agent"
