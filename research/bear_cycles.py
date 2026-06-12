"""Anatomía de los ciclos BAJISTAS de BTC: ¿dónde estamos en el bear actual?

Objetivo: medir de forma objetiva los bear markets históricos (techo→fondo), normalizar
sus trayectorias y ubicar el ciclo actual para decidir, con datos, si conviene buscar
largos de swing o si todavía es temprano.

Datos: BTC/USD diario desde 2013 (Bitstamp, research/btc_longhistory.py) — captura el
ATH de 2013 que Yahoo se pierde.

Definiciones objetivas:
  - Bear COMPLETADO: desde un ATH de ciclo hasta el mínimo posterior, cuando luego el
    precio se recupera por encima de ese ATH (nuevo ciclo). Se detecta sin hardcodear
    fechas: se marca bear cuando el precio cae > UMBRAL bajo el ATH vigente, y el fondo
    es el mínimo hasta que se supera ese ATH.
  - Ciclo ACTUAL: desde el ATH global (2025-10) hasta hoy; se reporta su drawdown y su
    mínimo-hasta-ahora SIN depender del umbral (el bear puede estar incompleto).

Métricas por bear: techo (fecha/precio), fondo (fecha/precio), drawdown máx %, duración
techo→fondo (días/semanas), y RSI mensual en el fondo. Trayectorias normalizadas a
tiempo∈[0,1] (0=techo, 1=fondo) y precio = % del ATH, para superponerlas.

Muestra: solo 3 bears previos → esto da RANGO/referencia, NO predicción.
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import btc_longhistory

DAY_MS = 86_400_000
BEAR_THR = 0.55          # caída mínima desde ATH para considerar "bear" (los 3 fueron >75%)


def detect_bears(ts, cl):
    """Devuelve (bears_completados, ciclo_actual). Cada bear: dict con índices y métricas."""
    n = len(cl)
    bears = []
    cur_ath = cl[0]; cur_ath_i = 0
    state = "up"
    top_i = trough_i = None
    trough = None
    for i in range(1, n):
        if state == "up":
            if cl[i] > cur_ath:
                cur_ath = cl[i]; cur_ath_i = i
            elif cl[i] < cur_ath * (1 - BEAR_THR):
                state = "down"; top_i = cur_ath_i; trough_i = i; trough = cl[i]
        else:
            if cl[i] < trough:
                trough = cl[i]; trough_i = i
            if cl[i] >= cur_ath:                      # recuperó el ATH viejo → ciclo nuevo
                bears.append(_bear_record(ts, cl, top_i, trough_i, completed=True))
                state = "up"; cur_ath = cl[i]; cur_ath_i = i
    # Ciclo actual: el ATH global vigente y el mínimo posterior hasta hoy.
    g_ath_i = int(np.argmax(cl))
    post = cl[g_ath_i:]
    min_off = int(np.argmin(post))
    cur = _bear_record(ts, cl, g_ath_i, g_ath_i + min_off, completed=False)
    cur["now_i"] = n - 1
    cur["now_price"] = cl[-1]
    cur["now_dd"] = cl[-1] / cl[g_ath_i] - 1.0
    cur["now_days"] = (ts[-1] - ts[g_ath_i]) / DAY_MS
    return bears, cur


def _bear_record(ts, cl, top_i, trough_i, completed):
    top_p, bot_p = cl[top_i], cl[trough_i]
    dur_days = (ts[trough_i] - ts[top_i]) / DAY_MS
    return {
        "top_i": top_i, "trough_i": trough_i, "completed": completed,
        "top_date": time.strftime("%Y-%m-%d", time.gmtime(ts[top_i] / 1000)),
        "bottom_date": time.strftime("%Y-%m-%d", time.gmtime(ts[trough_i] / 1000)),
        "top_price": top_p, "bottom_price": bot_p,
        "max_drawdown": bot_p / top_p - 1.0,
        "dur_days": dur_days, "dur_weeks": dur_days / 7.0,
    }


# --- RSI mensual ---------------------------------------------------------
def monthly_closes(ts, cl):
    buckets = {}
    for t, c in zip(ts, cl):
        gm = time.gmtime(t / 1000)
        key = gm.tm_year * 12 + (gm.tm_mon - 1)
        if key not in buckets or t > buckets[key][0]:
            buckets[key] = (t, c)
    keys = sorted(buckets)
    return [buckets[k][0] for k in keys], [buckets[k][1] for k in keys]


def rsi(values, period=14):
    n = len(values)
    out = [None] * n
    if n <= period:
        return out
    gains = [max(values[i] - values[i - 1], 0.0) for i in range(1, n)]
    losses = [max(values[i - 1] - values[i], 0.0) for i in range(1, n)]
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    out[period] = 100 - 100 / (1 + (ag / al if al > 0 else 99))
    for i in range(period + 1, n):
        ag = (ag * (period - 1) + gains[i - 1]) / period
        al = (al * (period - 1) + losses[i - 1]) / period
        out[i] = 100 - 100 / (1 + (ag / al if al > 0 else 99))
    return out


def rsi_at(mts, mrsi, target_ms):
    """RSI mensual del mes que contiene/precede a target_ms."""
    best = None
    for t, r in zip(mts, mrsi):
        if t <= target_ms + 31 * DAY_MS and r is not None:
            best = r
        if t > target_ms:
            break
    return best


# --- Trayectoria normalizada + overlay ASCII -----------------------------
def normalized_path(ts, cl, top_i, end_i, n_pts=40):
    """Devuelve (tfrac[], pct_of_ath[]) del techo (0) al fondo (1)."""
    seg = cl[top_i:end_i + 1]
    if len(seg) < 2:
        return [], []
    top = seg[0]
    xs = np.linspace(0, 1, n_pts)
    src = np.linspace(0, 1, len(seg))
    interp = np.interp(xs, src, [p / top for p in seg])
    return xs.tolist(), interp.tolist()


def ascii_overlay(cycle_bears, cur, labels):
    """Gráfico ASCII: % del ATH (eje y, 100%→fondo) vs tiempo normalizado (techo→fondo).
    Cada bear se dibuja como una curva continua (un char por columna)."""
    W, H = 56, 18
    grid = [[" "] * W for _ in range(H)]
    ymin = 0.10

    def plot(ch, xs, ys):
        # para cada columna, el valor más reciente de la curva
        col_val = {}
        for x, y in zip(xs, ys):
            if x < 0 or x > 1.02:
                continue
            col = min(W - 1, int(x / 1.02 * (W - 1)))
            col_val[col] = y
        for col, y in col_val.items():
            yy = max(0.0, min(1.0, (1.0 - y) / (1.0 - ymin)))
            rowi = min(H - 1, int(yy * (H - 1)))
            if grid[rowi][col] in (" ", ch):
                grid[rowi][col] = ch
            else:
                grid[rowi][col] = "*"   # solape de curvas

    med_dur = float(np.median([b["dur_days"] for b in cycle_bears]))
    for b, lab in zip(cycle_bears, labels):
        xs, ys = normalized_path(TS, CL, b["top_i"], b["trough_i"])
        plot(lab, xs, ys)
    cur_xs, cur_ys = normalized_path(TS, CL, cur["top_i"], cur["now_i"])
    cur_xs = [x * (cur["now_days"] / med_dur) for x in cur_xs]
    plot("A", cur_xs, cur_ys)

    lines = []
    for ri, row in enumerate(grid):
        pct = 100 - (ri / (H - 1)) * (100 - ymin * 100)
        lines.append(f"{pct:4.0f}% |" + "".join(row))
    lines.append("      +" + "-" * W)
    lines.append("       techo" + " " * (W - 14) + "fondo típico→")
    return "\n".join(lines)


TS = CL = None


CYCLE_MIN_WEEKS = 40    # un bear de CICLO dura ~1 año; menos = corrección intra-ciclo


def main():
    global TS, CL
    TS, CL = btc_longhistory.series()
    bears, cur = detect_bears(TS, CL)
    mts, mcl = monthly_closes(TS, CL)
    mrsi = rsi(mcl, 14)
    for b in bears:
        b["rsi_bottom"] = rsi_at(mts, mrsi, TS[b["trough_i"]])

    cycle_bears = [b for b in bears if b["dur_weeks"] >= CYCLE_MIN_WEEKS]
    intra = [b for b in bears if b["dur_weeks"] < CYCLE_MIN_WEEKS]

    print("=" * 74)
    print("  ANATOMÍA DE CICLOS BAJISTAS DE BTC (Bitstamp 2013→2026)")
    print("=" * 74)
    print(f"\n  Episodios de caída >{BEAR_THR*100:.0f}% detectados (objetivo, sin hardcodear):")
    print(f"    {'tipo':<13}{'techo':<12}{'fondo':<12}{'ATH$':>10}{'fondo$':>9}"
          f"{'DD%':>6}{'sem':>5}{'RSIfondo':>9}")
    for b in bears:
        tipo = "CICLO" if b["dur_weeks"] >= CYCLE_MIN_WEEKS else "corrección"
        rb = b["rsi_bottom"]
        print(f"    {tipo:<13}{b['top_date']:<12}{b['bottom_date']:<12}{b['top_price']:>10,.0f}"
              f"{b['bottom_price']:>9,.0f}{b['max_drawdown']*100:>6.0f}{b['dur_weeks']:>5.0f}"
              f"{(f'{rb:.0f}' if rb else '—'):>9}")
    print(f"    (la corrección 2013-04 es intra-bull, no un fondo de ciclo → fuera de la referencia)")

    # Estadística de referencia: SOLO los 3 bears de ciclo.
    dds = [b["max_drawdown"] for b in cycle_bears]
    durs = [b["dur_weeks"] for b in cycle_bears]
    rsis = [b["rsi_bottom"] for b in cycle_bears if b["rsi_bottom"]]
    labels = [str(i + 1) for i in range(len(cycle_bears))]
    print(f"\n  Referencia de FONDOS DE CICLO (n={len(cycle_bears)}): "
          f"DD {max(dds)*100:.0f}%..{min(dds)*100:.0f}% (mediana {np.median(dds)*100:.0f}%) · "
          f"duración {min(durs):.0f}..{max(durs):.0f} sem (mediana {np.median(durs):.0f}) · "
          f"RSI mensual fondo {min(rsis):.0f}..{max(rsis):.0f}")
    # Patrón de drawdowns decrecientes (diminishing returns).
    seq = " → ".join(f"{d*100:.0f}%" for d in dds)
    print(f"  Patrón: los fondos son cada vez MENOS profundos: {seq} (¿este ciclo más somero?)")

    # Ciclo actual.
    rsi_now = mrsi[-1]
    print("\n" + "-" * 74)
    print("  CICLO ACTUAL")
    print("-" * 74)
    print(f"    Techo: {cur['top_date']} ${cur['top_price']:,.0f}")
    print(f"    Hoy:   {time.strftime('%Y-%m-%d', time.gmtime(TS[-1]/1000))} "
          f"${cur['now_price']:,.0f}  →  drawdown {cur['now_dd']*100:+.0f}%")
    print(f"    Mínimo hasta ahora: ${cur['bottom_price']:,.0f} "
          f"({cur['bottom_date']}, {cur['max_drawdown']*100:+.0f}% desde ATH)")
    print(f"    Transcurrido: {cur['now_days']:.0f} días ({cur['now_days']/7:.0f} sem) "
          f"= {cur['now_days']/7/np.median(durs)*100:.0f}% de la duración mediana de bear")
    print(f"    RSI mensual hoy: {rsi_now:.0f}  (rango fondos previos {min(rsis):.0f}..{max(rsis):.0f})")

    # ¿Dónde cae el drawdown actual vs rango de fondos?
    dd_now = cur["now_dd"]
    print(f"\n  Posición del drawdown actual ({dd_now*100:.0f}%) vs fondos históricos "
          f"({max(dds)*100:.0f}%..{min(dds)*100:.0f}%):")
    frac_to_typical = dd_now / np.median(dds)
    print(f"    El drawdown actual es el {frac_to_typical*100:.0f}% del drawdown mediano de fondo.")

    leyenda = " · ".join(f"{lab}={b['top_date'][:7]}→{b['bottom_date'][:7]}"
                         for lab, b in zip(labels, cycle_bears))
    print("\n" + "-" * 74)
    print("  TRAYECTORIAS NORMALIZADAS (% del ATH vs tiempo techo→fondo)")
    print(f"  {leyenda} · A=actual  (* = solape de curvas)")
    print("-" * 74)
    print(ascii_overlay(cycle_bears, cur, labels))

    out = {"generated": int(time.time() * 1000), "source": "bitstamp_btcusd_1d",
           "cycle_bears": [{k: v for k, v in b.items() if k not in ("top_i", "trough_i")} for b in cycle_bears],
           "intra_cycle": [{k: v for k, v in b.items() if k not in ("top_i", "trough_i")} for b in intra],
           "current": {k: v for k, v in cur.items() if k not in ("top_i", "trough_i", "now_i")},
           "reference": {"dd_min": float(min(dds)), "dd_max": float(max(dds)),
                         "dd_median": float(np.median(dds)),
                         "dur_weeks_min": float(min(durs)), "dur_weeks_max": float(max(durs)),
                         "dur_weeks_median": float(np.median(durs)),
                         "rsi_bottom_min": float(min(rsis)), "rsi_bottom_max": float(max(rsis))},
           "rsi_now": float(rsi_now)}
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "bear_cycles.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, default=float)
    print("\n→ research/bear_cycles.json")


if __name__ == "__main__":
    main()
