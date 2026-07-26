#!/bin/sh
# Corre el estudio pareado "muro real vs nivel vacio" con lo que haya acumulado el
# archivo append-only del colector.
#
# Va por cron DIARIO en vez de una sola vez: el estudio mejora cada dia que pasa
# porque hay mas capturas, y asi no hay que acordarse de volver a lanzarlo. Es
# read-only sobre los datos y solo escribe su propio JSON de resultados y este log.
#
# Instalar (sin sudo, crontab del usuario):
#   (crontab -l 2>/dev/null; echo "7 19 * * * /home/hugo/Nexus/deploy/run_muros_study.sh") | crontab -
set -eu

RAIZ=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
LOG="$RAIZ/data/muros_estudio.log"
PY="$RAIZ/.venv/bin/python3"

[ -x "$PY" ] || PY=python3

{
    echo "===== $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
    "$PY" "$RAIZ/research/muros_vs_niveles_vacios.py" 2>&1 || \
        echo "el estudio fallo con codigo $?"
} >> "$LOG" 2>&1

# El log no puede crecer sin fin: se queda con lo ultimo. Se hace con un temporal
# porque truncar el archivo en el que se esta escribiendo pierde el contenido.
if [ "$(wc -l < "$LOG")" -gt 3000 ]; then
    tail -n 1500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi
