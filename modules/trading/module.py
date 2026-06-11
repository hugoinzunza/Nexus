"""Módulo de trading: co-piloto de mercado de cripto (solo lectura).

Qué hace:
  - Un hilo de fondo ("poller") consulta la API pública de Crypto.com cada
    pocos segundos y guarda el último estado del mercado en memoria.
  - Expone ese estado al navegador por dos vías:
      * /m/trading/api/state   → snapshot JSON (una foto)
      * /m/trading/api/stream  → SSE, empuja el estado en vivo
  - Calcula algunas "señales" simples (posición en el rango 24h, momentum,
    spread) como semilla de la futura inteligencia/alertas.

Importante: NO ejecuta operaciones. Es un observador.
"""

from __future__ import annotations

import json
import threading
import time

from core.module_base import NexusModule
from . import cryptocom


class TradingModule(NexusModule):
    slug = "trading"
    title = "Trading"
    description = "Co-piloto de mercado cripto en vivo: precios, libro de órdenes y velas (BTC, ETH)."
    icon = "📈"

    def __init__(self, context):
        super().__init__(context)
        cfg = self.config
        self.instruments = cfg.get("instruments", [
            {"name": "BTC_USDT", "label": "BTC/USDT"},
            {"name": "ETH_USDT", "label": "ETH/USDT"},
        ])
        self.poll_interval = int(cfg.get("poll_interval_seconds", 2))
        self.candle_refresh_every = int(cfg.get("candle_refresh_every", 6))
        self.book_depth = int(cfg.get("book_depth", 12))
        self.candle_timeframe = cfg.get("candle_timeframe", "1m")
        self.candle_count = int(cfg.get("candle_count", 200))

        # Estado compartido. Se reemplaza por referencia (atómico bajo el GIL),
        # así las lecturas desde otros hilos siempre ven una foto consistente.
        self._state = {
            "updated": 0,
            "upstream_ok": False,
            "error": None,
            "instruments": {},
        }
        self._stop = threading.Event()
        self._thread = None

    # --- Ciclo de vida -------------------------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._poll_loop, name="trading-poller", daemon=True)
        self._thread.start()
        self.context.log(f"trading: poller iniciado ({len(self.instruments)} instrumentos, cada {self.poll_interval}s)")

    def stop(self) -> None:
        self._stop.set()

    # --- Poller --------------------------------------------------------
    def _poll_loop(self) -> None:
        tick = 0
        candle_cache = {}  # instrumento → últimas velas (se refresca más espaciado)
        while not self._stop.is_set():
            instruments_state = {}
            ok = True
            error = None
            for inst in self.instruments:
                name = inst["name"]
                label = inst.get("label", name)
                try:
                    ticker = cryptocom.get_ticker(name)
                    book = cryptocom.get_book(name, self.book_depth)

                    # Las velas se refrescan cada N ticks (son más pesadas y
                    # cambian más lento que el precio).
                    if tick % self.candle_refresh_every == 0 or name not in candle_cache:
                        candle_cache[name] = cryptocom.get_candles(
                            name, self.candle_timeframe, self.candle_count)
                    candles = candle_cache.get(name, [])

                    instruments_state[name] = {
                        "instrument": name,
                        "label": label,
                        "ticker": ticker,
                        "book": book,
                        "candles": candles,
                        "signals": self._compute_signals(ticker, book, candles),
                    }
                except Exception as exc:  # noqa: BLE001
                    ok = False
                    error = str(exc)
                    # Conservamos el último estado bueno si lo había.
                    prev = self._state.get("instruments", {}).get(name)
                    if prev:
                        instruments_state[name] = prev

            self._state = {
                "updated": int(time.time() * 1000),
                "upstream_ok": ok,
                "error": error,
                "instruments": instruments_state,
            }
            tick += 1
            self._stop.wait(self.poll_interval)

    # --- Inteligencia (semilla) ---------------------------------------
    def _compute_signals(self, ticker: dict, book: dict, candles: list) -> dict:
        """Señales simples derivadas de los datos. Punto de partida para
        futuras alertas. Todo es informativo, nunca una recomendación."""
        last = ticker.get("last", 0.0)
        high = ticker.get("high", 0.0)
        low = ticker.get("low", 0.0)

        # Posición dentro del rango del día: 0% = en el mínimo, 100% = en el máximo.
        rng = high - low
        range_pos = ((last - low) / rng * 100) if rng > 0 else 50.0

        # Spread relativo (bid/ask) en puntos básicos.
        bid = ticker.get("bid", 0.0)
        ask = ticker.get("ask", 0.0)
        mid = (bid + ask) / 2 if (bid and ask) else last
        spread_bps = ((ask - bid) / mid * 10000) if mid > 0 else 0.0

        # Momentum corto: variación % sobre las últimas 15 velas.
        momentum = 0.0
        if len(candles) >= 16:
            ref = candles[-16]["c"]
            if ref > 0:
                momentum = (last - ref) / ref * 100

        # Desequilibrio del libro: ¿hay más presión compradora o vendedora?
        bid_vol = sum(l["qty"] for l in book.get("bids", [])[:10])
        ask_vol = sum(l["qty"] for l in book.get("asks", [])[:10])
        total = bid_vol + ask_vol
        book_imbalance = ((bid_vol - ask_vol) / total * 100) if total > 0 else 0.0

        return {
            "range_pos": round(range_pos, 1),
            "spread_bps": round(spread_bps, 2),
            "momentum_15": round(momentum, 3),
            "book_imbalance": round(book_imbalance, 1),
        }

    # --- API HTTP ------------------------------------------------------
    def api(self, subpath, query):
        if subpath == "state":
            body = json.dumps(self._state, ensure_ascii=False).encode("utf-8")
            return (200, "application/json; charset=utf-8", body)
        if subpath == "config":
            body = json.dumps({
                "instruments": self.instruments,
                "poll_interval": self.poll_interval,
                "timeframe": self.candle_timeframe,
            }, ensure_ascii=False).encode("utf-8")
            return (200, "application/json; charset=utf-8", body)
        return None

    def sse(self, subpath, query):
        if subpath != "stream":
            return None
        return self._stream()

    def _stream(self):
        """Generador SSE: empuja el estado actual cada intervalo de poll."""
        # Evento inicial inmediato para que el navegador pinte algo enseguida.
        yield self._sse_event(self._state)
        last_sent = self._state.get("updated")
        idle = 0
        while not self._stop.is_set():
            time.sleep(max(0.5, self.poll_interval / 2))
            updated = self._state.get("updated")
            if updated != last_sent:
                yield self._sse_event(self._state)
                last_sent = updated
                idle = 0
            else:
                idle += 1
                if idle >= 6:  # comentario keep-alive para no cerrar la conexión
                    yield ": keep-alive\n\n"
                    idle = 0

    @staticmethod
    def _sse_event(state: dict) -> str:
        return "data: " + json.dumps(state, ensure_ascii=False) + "\n\n"

    # --- Salud ---------------------------------------------------------
    def health(self) -> dict:
        return {
            "slug": self.slug,
            "status": "ok" if self._state.get("upstream_ok") else "degradado",
            "upstream_ok": self._state.get("upstream_ok"),
            "last_update_ms": self._state.get("updated"),
            "instruments": list(self._state.get("instruments", {}).keys()),
        }


def get_module(context):
    return TradingModule(context)
