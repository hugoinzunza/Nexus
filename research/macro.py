"""Datos macro (SPX, VIX) y derivados de régimen, para usarlos como filtro de las
entradas SMC POI.

Fuente: API pública de gráficos de Yahoo Finance (query1.finance.yahoo.com/v8/finance/chart).
Sin clave. Cacheamos en research/data_macro/ para no rebajar lo mismo cada vez.

Series diarias:
  - ^GSPC (S&P 500)  → nivel de cierre.
  - ^VIX  (volatilidad implícita)  → nivel de cierre.
  - BTC-USD (diario, para correlación BTC↔SPX y régimen de tendencia de BTC).

Derivados (todos anti-repaint: el valor de un día usa solo datos HASTA ese cierre):
  - vix_close[d]          : nivel del VIX al cierre del día d.
  - btc_spx_corr30[d]     : correlación de Pearson de retornos diarios BTC vs SPX,
                            ventana de 30 días terminando en d (solo días pasados).
  - btc_ma200[d]          : media móvil 200d del cierre de BTC (régimen de tendencia).
  - btc_above_ma200[d]    : 1 si el cierre de BTC del día d está sobre su MA200d.

Para alinear con un timestamp intradía de cripto (24/7) usamos el ÚLTIMO día de
mercado cuyo cierre ya ocurrió antes del timestamp (sin mirar el futuro). Los
mercados tradicionales no operan finde/feriados: se arrastra el último valor.
"""
from __future__ import annotations

import bisect
import json
import os
import time
import urllib.request

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_macro")
DAY_MS = 86_400_000

# Hora aprox. de cierre de NYSE en UTC (~21:00 UTC, 16:00 ET). Usamos el cierre del
# día de mercado: un valor diario "vale" recién pasada esa hora (anti-repaint).
MARKET_CLOSE_UTC_H = 21


def _fetch_yahoo(symbol: str, rng: str = "6y") -> list:
    """Descarga velas diarias {t_ms, c} desde Yahoo. t_ms = timestamp de cierre."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={rng}&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.load(r)
    res = d["chart"]["result"][0]
    ts = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    out = []
    for t, c in zip(ts, closes):
        if c is None:
            continue
        # Yahoo entrega el timestamp en SEGUNDOS y a la APERTURA del día de mercado;
        # el dato del cierre solo es conocible tras el cierre. Pasamos a ms y sumamos
        # hasta la hora de cierre UTC (anti-repaint).
        t = int(t) * 1000
        day0 = (t // DAY_MS) * DAY_MS
        out.append({"t": day0 + MARKET_CLOSE_UTC_H * 3_600_000, "c": float(c)})
    out.sort(key=lambda x: x["t"])
    return out


def load(symbol: str, fname: str, rng: str = "6y", force: bool = False) -> list:
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, fname)
    if os.path.isfile(path) and not force:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    data = _fetch_yahoo(symbol, rng)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    return data


def _pearson(xs, ys) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return 0.0
    return sxy / (sxx * syy) ** 0.5


class Macro:
    """Series macro alineables a cualquier timestamp en ms (anti-repaint)."""

    def __init__(self, force: bool = False):
        spx = load("%5EGSPC", "spx_1d.json", force=force)
        vix = load("%5EVIX", "vix_1d.json", force=force)
        btc = load("BTC-USD", "btc_1d.json", force=force)

        # Indexar por timestamp de cierre.
        self.spx = spx
        self.vix = vix
        self.btc = btc
        self.vix_t = [r["t"] for r in vix]
        self.vix_c = [r["c"] for r in vix]

        # Mapa fecha(día UTC)→cierre para alinear BTC y SPX por día de mercado común.
        def by_day(series):
            return {r["t"] // DAY_MS: r["c"] for r in series}

        spx_day = by_day(spx)
        btc_day = by_day(btc)
        common_days = sorted(set(spx_day) & set(btc_day))

        # Retornos diarios alineados en días de mercado comunes.
        rets_btc, rets_spx, ret_days = [], [], []
        for i in range(1, len(common_days)):
            d0, d1 = common_days[i - 1], common_days[i]
            rb = btc_day[d1] / btc_day[d0] - 1.0
            rs = spx_day[d1] / spx_day[d0] - 1.0
            rets_btc.append(rb)
            rets_spx.append(rs)
            ret_days.append(d1)

        # Correlación 30d móvil (anti-repaint: usa los 30 retornos hasta ese día).
        W = 30
        self.corr_t = []
        self.corr_v = []
        for i in range(len(ret_days)):
            if i < W:
                continue
            c = _pearson(rets_btc[i - W:i], rets_spx[i - W:i])
            # timestamp = cierre de ese día de mercado
            self.corr_t.append(ret_days[i] * DAY_MS + MARKET_CLOSE_UTC_H * 3_600_000)
            self.corr_v.append(c)

        # MA200 de BTC diario + flag sobre/bajo.
        self.btc_t = [r["t"] for r in btc]
        self.btc_c = [r["c"] for r in btc]
        self.btc_ma200 = []
        s = 0.0
        for i, c in enumerate(self.btc_c):
            s += c
            if i >= 200:
                s -= self.btc_c[i - 200]
            self.btc_ma200.append(s / 200 if i >= 199 else None)

    @staticmethod
    def _last_before(ts_list, val_list, ts_ms):
        """Último valor cuyo timestamp <= ts_ms (sin mirar el futuro). None si no hay."""
        idx = bisect.bisect_right(ts_list, ts_ms) - 1
        if idx < 0:
            return None
        return val_list[idx]

    def vix_at(self, ts_ms):
        return self._last_before(self.vix_t, self.vix_c, ts_ms)

    def corr_at(self, ts_ms):
        return self._last_before(self.corr_t, self.corr_v, ts_ms)

    def btc_above_ma200_at(self, ts_ms):
        idx = bisect.bisect_right(self.btc_t, ts_ms) - 1
        if idx < 0 or self.btc_ma200[idx] is None:
            return None
        return 1 if self.btc_c[idx] > self.btc_ma200[idx] else 0


if __name__ == "__main__":
    m = Macro(force=True)
    print("SPX:", len(m.spx), "VIX:", len(m.vix), "BTC:", len(m.btc))
    print("corr puntos:", len(m.corr_v))
    # Muestra reciente
    now = int(time.time() * 1000)
    print("VIX hoy:", m.vix_at(now))
    print("corr BTC-SPX 30d:", m.corr_at(now))
    print("BTC sobre MA200:", m.btc_above_ma200_at(now))
    # Distribución VIX
    vs = sorted(m.vix_c)
    print("VIX percentiles 25/50/75:", round(vs[len(vs)//4], 1),
          round(vs[len(vs)//2], 1), round(vs[3*len(vs)//4], 1))
    cs = sorted(m.corr_v)
    print("corr percentiles 25/50/75:", round(cs[len(cs)//4], 2),
          round(cs[len(cs)//2], 2), round(cs[3*len(cs)//4], 2))
