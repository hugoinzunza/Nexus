#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/.build/NexUX Command Center.app"
PORT="${NEXUX_COMMAND_CENTER_PORT:-8812}"
URL="${NEXUX_COMMAND_CENTER_URL:-http://127.0.0.1:${PORT}/m/command-center/}"
HEALTH_URL="${NEXUX_COMMAND_CENTER_HEALTH_URL:-http://127.0.0.1:${PORT}/health}"
LOG_DIR="$ROOT/logs"
LOG_FILE="$LOG_DIR/command-center-local.log"
PYTHON="$ROOT/.venv/bin/python"
SERVICE_LABEL="com.hugo.nexux-command-center"
SERVICE_DOMAIN="gui/$(id -u)"
SERVICE_SOURCE="$ROOT/deploy/$SERVICE_LABEL.plist"
SERVICE_TARGET="$HOME/Library/LaunchAgents/$SERVICE_LABEL.plist"

start_backend_service() {
    mkdir -p "$LOG_DIR" "$HOME/Library/LaunchAgents"

    local service_changed=0
    if ! cmp -s "$SERVICE_SOURCE" "$SERVICE_TARGET" 2>/dev/null; then
        cp "$SERVICE_SOURCE" "$SERVICE_TARGET"
        service_changed=1
    fi

    if launchctl print "$SERVICE_DOMAIN/$SERVICE_LABEL" >/dev/null 2>&1; then
        if (( service_changed )); then
            launchctl bootout "$SERVICE_DOMAIN/$SERVICE_LABEL"
            launchctl bootstrap "$SERVICE_DOMAIN" "$SERVICE_TARGET"
        else
            launchctl kickstart -k "$SERVICE_DOMAIN/$SERVICE_LABEL"
        fi
    else
        launchctl enable "$SERVICE_DOMAIN/$SERVICE_LABEL"
        launchctl bootstrap "$SERVICE_DOMAIN" "$SERVICE_TARGET"
    fi
}

ensure_backend() {
    if curl --silent --show-error --fail --max-time 2 "$HEALTH_URL" >/dev/null 2>&1; then
        return
    fi

    if [[ ! -x "$PYTHON" ]]; then
        print -u2 "No se encontro el Python local de NexUX: $PYTHON"
        exit 1
    fi

    if [[ "$PORT" != "8812" ]]; then
        print -u2 "El servicio local persistente usa el puerto 8812, no $PORT"
        exit 1
    fi
    start_backend_service

    for _attempt in {1..60}; do
        if curl --silent --show-error --fail --max-time 2 "$HEALTH_URL" >/dev/null 2>&1; then
            return
        fi
        sleep 0.25
    done

    print -u2 "NexUX no pudo iniciar en $HEALTH_URL"
    tail -20 "$LOG_FILE" >&2 || true
    exit 1
}

if [[ "${NEXUX_COMMAND_CENTER_AUTO_START:-1}" != "0" ]]; then
    ensure_backend
fi
"$ROOT/tools/build_command_center_shell.command" >/dev/null
open -na "$APP" --args "$URL"
