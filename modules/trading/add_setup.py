"""Carga MANUAL de una entrada (del profe) al forward-test / cuenta paper.

POSTea el plan a la app de Nexus corriendo (que lo registra en su SetupStore en
caliente y lo sincroniza a Railway vía el colector). NO coloca órdenes — es paper.

Uso:
    python3 -m modules.trading.add_setup --pair BTC --dir long \
        --entry 64000 --sl 62960 --tp 67800 [--label "profe 06-13"]

El par acepta BTC / BTCUSDT / BTC_USDT (idem ETH). El SL/TP son los que dé el profe
(p. ej. SL 2%). Toma la URL/token de NEXUS_INGEST_URL/TOKEN o deploy/collector.env
(por defecto apunta a la app local http://localhost:8800).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENV_CANDIDATES = [
    os.environ.get("NEXUS_COLLECTOR_ENV", ""),
    os.path.expanduser("~/.nexus/binance.env"),
    os.path.join(ROOT, "deploy", "collector.env"),
]


def _load_env():
    for path in ENV_CANDIDATES:
        if path and os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


def main():
    _load_env()
    ap = argparse.ArgumentParser(description="Agrega una entrada manual del profe al forward-test.")
    ap.add_argument("--pair", required=True, help="BTC / ETH / BTCUSDT / BTC_USDT")
    ap.add_argument("--dir", required=True, choices=["long", "short", "largo", "corto"])
    ap.add_argument("--entry", required=True, type=float)
    ap.add_argument("--sl", required=True, type=float)
    ap.add_argument("--tp", required=True, type=float)
    ap.add_argument("--label", default="profe")
    ap.add_argument("--url", default=os.environ.get("NEXUS_TRADING_URL", "http://localhost:8800"))
    args = ap.parse_args()

    base = args.url.rstrip("/")
    # Si dieron la URL de ingesta del Diario, derivamos la base del host.
    if "/m/journal" in base:
        base = base.split("/m/journal")[0]
    url = base + "/m/trading/api/manual_setup"
    payload = {"pair": args.pair, "dir": args.dir, "entry": args.entry,
               "sl": args.sl, "tp": args.tp, "label": args.label}
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    token = os.environ.get("NEXUS_INGEST_TOKEN", "").strip()
    if token:
        headers["X-Nexus-Token"] = token
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            out = json.load(resp)
        sl_pct = out.get("sl_pct")
        print(f"✓ registrada: {args.pair} {args.dir} @ {args.entry} | SL {args.sl} "
              f"({sl_pct}%) | TP {args.tp} | R:R {out.get('rr')} | estado {out.get('status')}")
    except urllib.error.HTTPError as exc:
        print(f"✗ error {exc.code}: {exc.read().decode('utf-8', 'ignore')}")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ no se pudo conectar a {url}: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
