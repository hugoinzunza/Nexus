"""Refresca la historia de velas persistida y la publica a Railway (deploy).

POR QUÉ EXISTE: Railway está geo-bloqueado de Binance (HTTP 451), así que la
historia profunda que usan los POIs viaja a producción versionada en git
(data/klines_*.json). Esos archivos son una FOTO; este script, corriendo en el
Mac mini (que sí llega a Binance), los mantiene frescos:

  1. baja SOLO lo nuevo de Binance (binance.fetch_klines es incremental),
  2. si algún archivo cambió, hace git add/commit/push → Railway redeploya.

La historia vieja no cambia; el borde reciente además lo tapa el merge en vivo
(Crypto.com) en Railway. Por eso basta con correr esto MENSUAL y acotado a las
TF altas de los instrumentos en producción (lo demás solo infla el repo: cada
push reescribe el JSON completo, git no lo diffea).

Uso:
    python -m modules.trading.refresh_klines               # BTC+ETH, 1d/4h/1h
    python -m modules.trading.refresh_klines --symbols BTCUSDT,ETHUSDT
    python -m modules.trading.refresh_klines --intervals 1d,4h,1h,15m
    python -m modules.trading.refresh_klines --no-push     # solo actualizar/commitear
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

WT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if WT not in sys.path:
    sys.path.insert(0, WT)

from modules.trading import binance  # noqa: E402

# Por defecto: lo que SIRVE en producción (config/nexus.json → BTC, ETH) y las TF
# que usan los POIs profundos. 15m queda fuera del refresco rutinario (85 MB, solo
# lo usan los backtests; se puede pedir con --intervals).
DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT"]
DEFAULT_INTERVALS = ["1d", "4h", "1h"]
YEARS = 4.0


def log(msg: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=WT, capture_output=True, text=True)


def refresh(symbols, intervals, push: bool) -> int:
    data_dir = os.path.join(WT, "data")
    ok, fail = 0, 0
    for sym in symbols:
        for iv in intervals:
            try:
                candles = binance.fetch_klines(sym, iv, years=YEARS,
                                               data_dir=data_dir, log=log)
                ok += 1
                last = time.strftime("%Y-%m-%d %H:%M", time.gmtime(candles[-1]["t"] / 1000)) \
                    if candles else "s/d"
                log(f"{sym} {iv}: {len(candles)} velas (hasta {last})")
            except Exception as exc:  # noqa: BLE001 - una TF caída no aborta el resto
                fail += 1
                log(f"{sym} {iv}: ERROR {type(exc).__name__}: {exc}")

    # ¿Cambió algo en disco? Si no, no hay nada que publicar.
    status = _git("status", "--porcelain", "--", "data/klines_*.json")
    if not status.stdout.strip():
        log("Sin cambios en los klines: nada que commitear.")
        return 0 if fail == 0 else 1

    add = _git("add", "data/klines_*.json")
    if add.returncode != 0:
        log(f"git add falló: {add.stderr.strip()}")
        return 1
    stamp = time.strftime("%Y-%m-%d %H:%M")
    msg = f"Klines: refresco automático {stamp} ({','.join(symbols)} · {','.join(intervals)})"
    commit = _git("commit", "-m", msg)
    if commit.returncode != 0:
        log(f"git commit falló: {commit.stderr.strip() or commit.stdout.strip()}")
        return 1
    log(f"Commit: {msg}")

    if not push:
        log("--no-push: commit local hecho, no se publica.")
        return 0
    pushed = _git("push", "origin", "HEAD")
    if pushed.returncode != 0:
        log(f"git push falló (¿clave SSH en el entorno de launchd?): "
            f"{pushed.stderr.strip()}")
        return 1
    log("Push OK → Railway redeploy con data fresca.")
    return 0 if fail == 0 else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="Refresca y publica la historia de velas.")
    ap.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS),
                    help="Símbolos Binance separados por coma (def: BTCUSDT,ETHUSDT)")
    ap.add_argument("--intervals", default=",".join(DEFAULT_INTERVALS),
                    help="Intervalos separados por coma (def: 1d,4h,1h)")
    ap.add_argument("--no-push", action="store_true", help="No hacer git push")
    args = ap.parse_args()
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    intervals = [i.strip() for i in args.intervals.split(",") if i.strip()]
    sys.exit(refresh(symbols, intervals, push=not args.no_push))


if __name__ == "__main__":
    main()
