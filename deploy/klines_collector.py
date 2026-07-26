#!/usr/bin/env python3
"""Empuja klines de Binance Futuros desde el VPS hacia NexUX.

POR QUÉ EXISTE: Railway está geo-bloqueado por Binance. Verificado el 2026-07-26:
`https://fapi.binance.com/fapi/v1/klines` responde **HTTP 451** ("Service unavailable
from a restricted location") al servidor de Railway, y responde normal desde el VPS
(Hetzner) en menos de medio segundo.

El módulo `inteligencia` pedía las velas al exchange desde el proceso web, y eso
rompía el patrón del proyecto: el VPS recolecta, Railway muestra. Esto lo devuelve a
su lugar, igual que hacen `visual_collector.py` (CoinGlass) y el colector de cuenta.

QUÉ NO HACE: no firma nada, no lee credenciales de Binance, no toca el bot ni el
dry-run. Solo GET públicos y un POST autenticado con `NEXUS_INGEST_TOKEN`.

Uso:
    NEXUS_INGEST_TOKEN=... ./klines_collector.py --destino https://nexux.cl
    ./klines_collector.py --dry-run          # imprime y no publica

Instalación en el VPS (pendiente de autorización de Hugo):
    systemd timer cada 10 min, como `nexus-coinglass-visual.timer`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

FAPI = "https://fapi.binance.com/fapi/v1/klines"

# Los pares del módulo. Se declaran acá y se validan otra vez del lado del servidor:
# que el colector mande algo no significa que el servidor deba creerlo.
PARES = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT")

# Cuántas velas por temporalidad. El 1d va con 1.500 a propósito: cubre desde
# 2022-06-18 (medido), o sea TODAS las aperturas anuales que la vista necesita para
# anclar la rejilla. Las otras van más cortas porque solo alimentan el gráfico.
SERIES = (("15m", 500), ("1h", 500), ("4h", 500), ("1d", 1_500))

TIMEOUT = 20
REINTENTOS = 3


def _get(symbol: str, tf: str, limit: int) -> list[dict]:
    """GET público con reintento y espera creciente.

    El reintento no es decorativo: el colector visual perdía un ciclo entero cada vez
    que Binance devolvía un 429, hasta que se le puso backoff. Mismo remedio acá,
    antes de que pase.
    """
    url = f"{FAPI}?symbol={symbol}&interval={tf}&limit={limit}"
    espera, ultimo = 2.0, None
    for intento in range(1, REINTENTOS + 1):
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
                filas = json.load(resp)
            return [{"t": int(f[0]), "o": float(f[1]), "h": float(f[2]),
                     "l": float(f[3]), "c": float(f[4]), "v": float(f[5])}
                    for f in filas]
        except Exception as exc:  # noqa: BLE001
            ultimo = exc
            if intento >= REINTENTOS:
                break
            print(f"  {symbol} {tf}: intento {intento} falló ({type(exc).__name__}: "
                  f"{str(exc)[:60]}); reintento en {espera:.0f}s", file=sys.stderr)
            time.sleep(espera)
            espera *= 2
    print(f"  {symbol} {tf}: SIN DATOS tras {REINTENTOS} intentos ({ultimo})",
          file=sys.stderr)
    return []


def recolectar() -> dict:
    series, fallos = {}, 0
    for symbol in PARES:
        for tf, limit in SERIES:
            velas = _get(symbol, tf, limit)
            if velas:
                series[f"{symbol}:{tf}"] = velas
            else:
                fallos += 1
            # Cortesía con el rate limit: 20 requests por corrida es poco, pero
            # dispararlos juntos es justo lo que produjo la ráfaga que nos costó los
            # -1021 en el colector de cuenta.
            time.sleep(0.2)
    return {"captured_at": datetime.now(timezone.utc).isoformat(),
            "series": series, "fallos": fallos}


def publicar(payload: dict, destino: str, token: str) -> None:
    url = destino.rstrip("/") + "/m/inteligencia/api/klines-ingest"
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        url, data=raw, method="POST",
        headers={"Content-Type": "application/json", "X-Nexus-Token": token})
    with urllib.request.urlopen(req, timeout=60) as resp:
        print(f"publicado: {resp.status} {resp.read()[:200].decode(errors='replace')}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--destino", default=os.environ.get("NEXUS_DESTINO", "https://nexux.cl"))
    ap.add_argument("--token", default=os.environ.get("NEXUS_INGEST_TOKEN", ""))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    payload = recolectar()
    n_series = len(payload["series"])
    n_velas = sum(len(v) for v in payload["series"].values())
    print(f"{n_series} series, {n_velas} velas, {payload['fallos']} fallos")

    if not n_series:
        # Publicar un payload vacío borraría de hecho lo que hay servido. Mejor fallar
        # ruidoso y que la pantalla siga mostrando lo último bueno con su edad visible.
        print("nada que publicar: no se pisa lo que ya está servido", file=sys.stderr)
        return 1
    if args.dry_run:
        muestra = next(iter(payload["series"]))
        print(f"dry-run: {muestra} -> {len(payload['series'][muestra])} velas, "
              f"última {payload['series'][muestra][-1]}")
        return 0
    if not args.token:
        print("NEXUS_INGEST_TOKEN requerido para publicar", file=sys.stderr)
        return 2
    try:
        publicar(payload, args.destino, args.token)
    except urllib.error.HTTPError as exc:
        print(f"publicación falló: HTTP {exc.code} "
              f"{exc.read()[:200].decode(errors='replace')}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
