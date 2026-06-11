#!/bin/bash
# Entrypoint de Nexus para Railway (y para correr en producción local).
# Arranca FastAPI/uvicorn en el puerto que Railway provee como $PORT.
# Mismo estilo que apps/proteq-hub de ClaudeOS.

set -e

PORT="${PORT:-8800}"

echo "[start] Arrancando Nexus en 0.0.0.0:$PORT"
exec uvicorn core.app:app --host 0.0.0.0 --port "$PORT"
