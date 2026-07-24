"""Registro persistente de SETUPS del indicador SMC en vivo (forward-test).

Cada vez que el indicador genera un PLAN válido (el campo `tpsl` de smc_live), se
registra acá deduplicado. Después se hace seguimiento del resultado contra el precio
en vivo:
  - el precio entra a la zona del POI  → "activo" (la entrada se llenó),
  - llega al TP                        → "ganada"  (R = +R:R),
  - llega al SL                        → "perdida" (R = -1),
  - nunca se llena y se va / expira    → "anulada" (no contó como trade),
  - en curso sin tocar la zona aún     → "pendiente".

Es forward-test honesto: un plan solo cuenta como ganada/perdida si el precio
REALMENTE entró a la zona de entrada. Persiste en disco (JSON) para acumular en el
tiempo. El archivo vive en data/ (efímero en Railway entre despliegues, permanente
en el Mac mini, donde el autostart corre NexUX de forma continua)."""
from __future__ import annotations

import json
import math
import os
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(ROOT, "data")
SETUPS_PATH = os.path.join(DATA_DIR, "setups.json")

# Buffer para considerar que el precio "entró" a la zona del POI (activación): 0.05%.
_ZONE_BUF = 0.0005
# Expiración de un plan PENDIENTE que nunca se llena (horas), según la TF del POI.
_EXPIRE_HOURS = {"15m": 24, "1h": 96, "4h": 240, "1D": 720}
_DEFAULT_EXPIRE_H = 168

# Horas que dura UNA vela de cada TF de POI (para traducir cooldowns a tiempo real).
_TF_HOURS = {"15m": 0.25, "1h": 1.0, "4h": 4.0, "1D": 24.0}
# GUARDIA DE RE-ENTRADA: tras CERRAR un setup (ganada/perdida), no re-registrar la MISMA
# zona (key) hasta que pasen estas velas de su TF de POI. El dedup normal solo bloquea
# mientras hay uno ABIERTO; sin esta guardia, una zona que stopea se re-registra al
# instante y el forward-test cuenta re-entradas correlacionadas a la misma zona como
# trades independientes (la zona BTC se re-registró 6 veces en 27h → sobre-conteo que
# distorsiona retorno, win rate y equity). Una re-entrada legítima MÁS TARDE sí cuenta.
_REENTRY_COOLDOWN_BARS = 12

_OPEN = ("pendiente", "activo")
_CLOSED = ("ganada", "perdida", "anulada")

# Versionado de la semántica de entrada. V1 activaba al tocar cualquier borde del
# POI pero contabilizaba el fill en el punto medio; eso acreditó fills que nunca
# ocurrieron. V2 exige un cruce causal del precio de entrada planificado.
ENTRY_MODEL_V1 = "zone_touch_v1"
ENTRY_MODEL_V2 = "midpoint_touch_v2"
CURRENT_PHASE_ID = "phase1_v2_2026-07-18"


def is_entry_v2(s: dict) -> bool:
    return s.get("entry_model") == ENTRY_MODEL_V2


def _key(pair: str, plan: dict) -> str:
    """Clave de deduplicación: par + TF del POI + dirección + extremo de la zona."""
    return f"{pair}:{plan['tf']}:{plan['dir']}:{round(plan['entry_lo'], 2)}"


def _zones_overlap(a_lo, a_hi, b_lo, b_hi) -> bool:
    """¿Se solapan dos zonas [lo, hi]? (intervalos). Dos POIs de la misma dirección
    cuyas zonas se solapan son la MISMA idea aunque su key difiera (por centavos en el
    extremo o por otra TF) — abrir ambos sería doble riesgo sobre un mismo SL."""
    if None in (a_lo, a_hi, b_lo, b_hi):
        return False
    return a_lo <= b_hi and b_lo <= a_hi


def load_all(path: str = SETUPS_PATH) -> list:
    """Lee los setups del disco (fresco, para el lector del Diario)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001 - archivo ausente o corrupto → lista vacía
        return []


def _perf(closed: list) -> dict:
    """Desempeño (win rate, R prom, PF, R acum) de un set de setups cerrados."""
    wins = [s for s in closed if s["status"] == "ganada"]
    losses = [s for s in closed if s["status"] == "perdida"]
    n = len(closed)
    gross_win = sum(s.get("result_r") or 0.0 for s in wins)
    gross_loss = abs(sum(s.get("result_r") or 0.0 for s in losses))  # = nº de pérdidas
    total_r = sum(s.get("result_r") or 0.0 for s in closed)
    pf = round(gross_win / gross_loss, 2) if gross_loss > 0 else None
    return {
        "cerradas": n,
        "ganadas": len(wins),
        "perdidas": len(losses),
        "win_rate": round(len(wins) / n * 100, 1) if n else None,
        "avg_r": round(total_r / n, 2) if n else None,
        "total_r": round(total_r, 2),
        "pf": pf,
    }


def summarize(setups: list) -> dict:
    """Resumen tipo diario: win rate, R promedio y profit factor de lo cerrado.
    Solo ganada/perdida cuentan para el desempeño; anuladas se informan aparte.
    Incluye el desglose CON filtro de régimen vs SIN filtro (objetivo del forward-test)."""
    closed = [s for s in setups if s["status"] in ("ganada", "perdida")]
    out = {
        "total": len(setups),
        "pendientes": sum(1 for s in setups if s["status"] == "pendiente"),
        "activos": sum(1 for s in setups if s["status"] == "activo"),
        "anuladas": sum(1 for s in setups if s["status"] == "anulada"),
    }
    out.update(_perf(closed))
    # Comparativa de régimen: los que pasaron el filtro (regime_ok True) vs los que no.
    out["con_filtro"] = _perf([s for s in closed if s.get("regime_ok") is True])
    out["sin_filtro"] = _perf([s for s in closed if s.get("regime_ok") is False])
    # Comparativa CDC: setups donde el cambio de carácter APARECIÓ (en el POI, en la
    # dirección correcta, mientras el setup estaba abierto) vs donde nunca apareció.
    out["con_cdc"] = _perf([s for s in closed if s.get("cdc_ok") is True])
    out["sin_cdc"] = _perf([s for s in closed if s.get("cdc_ok") is False])
    # Comparativa por FUENTE: entradas del profe (manuales) vs las del indicador.
    out["profe"] = _perf([s for s in closed if s.get("source") == "profe"])
    out["indicador"] = _perf([s for s in closed if s.get("source") in (None, "indicador")])
    out["bta_paper"] = _perf([s for s in closed if s.get("source") == "bta_paper"
                              or s.get("bta_paper") is True])
    return out


# --- Cuenta PAPER (forward-test con dinero simulado) -----------------------
# Convierte los setups cerrados en P&L en USD con sizing por riesgo, compuesto.
# Es la config que el estudio nocturno marcó como sana (ver
# research/veredicto_estrategia_2026-06-13.md): ~2% de riesgo por trade (≈3x
# efectivo con el SL ajustado), NO 10x/20x. Dinero SIMULADO: valida la ejecución
# antes de arriesgar real.
PAPER_CAPITAL = 38000.0     # capital inicial (USD) — el de Hugo en Binance
PAPER_RISK_PCT = 0.02       # riesgo por trade (2% del capital, compuesto)
PAPER_COST_RATE = 0.0014    # (legacy/override) comisión taker ambos lados + slippage
# Modelo de costo MAKER-AWARE (real para SMC): la entrada es una orden LÍMITE en la
# zona POI (maker), el TP también (maker); solo el SL es market (taker) + slippage.
PAPER_MAKER_FEE = 0.0002    # 0.02%/lado (orden límite)
PAPER_TAKER_FEE = 0.0005    # 0.05%/lado (orden market: SL/trailing)
PAPER_SLIPPAGE = 0.0002     # 0.02% por fill market


def _cost_fraction(won: bool, override=None) -> float:
    """Costo round-trip como fracción del nocional. Entrada siempre maker; salida
    maker si ganó (TP límite) o taker+slippage si perdió (SL market). `override`
    fuerza un cost_rate plano (para análisis de sensibilidad)."""
    if override is not None:
        return override
    exit_cost = PAPER_MAKER_FEE if won else (PAPER_TAKER_FEE + PAPER_SLIPPAGE)
    return PAPER_MAKER_FEE + exit_cost


# Cuenta SELECTIVA = HIPÓTESIS en validación (no un edge probado): el subgrupo que mejor
# se veía en el laboratorio — zona POI de timeframe ALTO (4h/1D) + disciplina premium/
# descuento (OTE) + R:R ≥ 5. OJO: son filtros elegidos MIRANDO los resultados (posible
# sobreajuste); su muestra en vivo es minúscula. La cuenta completa registra todo en
# paralelo, para comparar calidad vs cantidad — la decisión se toma con muestra suficiente.
SELECTIVE_POI_TFS = ("4h", "1D")
SELECTIVE_MIN_RR = 5.0

# Plan de SALIDA del bot: parciales + break-even (la estrategia validada que GANA en
# todo vs el TP único). Legs intermedios (R, fracción) antes del runner; el resto se
# deja correr al TP lejano. El SL pasa a break-even tras llenar PARTIAL_BE_AFTER legs.
PARTIAL_LEGS = [(1.0, 0.5), (2.0, 0.25)]   # TP1: 1R cierra 50% · TP2: 2R cierra 25%
PARTIAL_BE_AFTER = 1                         # break-even tras el 1er parcial (TP1)
PARTIAL_TRAIL_R = 1.0                        # runner: trailing stop a 1R del mejor precio
_LEG_NAMES = {0: "TP1", 1: "TP2"}


def is_selective(s: dict) -> bool:
    return (s.get("poi_tf") in SELECTIVE_POI_TFS
            and s.get("disc_ok") is True
            and (s.get("rr") or 0) >= SELECTIVE_MIN_RR)


def paper_account(setups: list, capital: float = PAPER_CAPITAL,
                  risk_pct: float = PAPER_RISK_PCT,
                  cost_rate=None,
                  selector=None, annotate: bool = True, tag: str = "") -> dict:
    """Cuenta de PAPER TRADING sobre los setups CERRADOS (ganada/perdida): cada
    trade arriesga `risk_pct` del capital vigente (compuesto); el P&L en USD es
    R_neto × riesgo, con R_neto = result_r − costo (costo_R = cost_rate / SL%).
    Devuelve equity final, P&L, retorno %, drawdown máximo y la curva. Es dinero
    simulado — el bot NO coloca órdenes.

    `selector`: si se da, solo cuenta los setups que lo cumplen (cuenta selectiva).
    `annotate`: si False, no escribe paper_* en los setups (para no pisar la cuenta
    completa cuando se calcula una segunda cuenta filtrada)."""
    keep = selector or (lambda s: True)
    eligible = sorted(
        [s for s in setups
         if s["status"] in ("ganada", "perdida")
         and s.get("result_r") is not None and s.get("ts_closed") and keep(s)],
        key=lambda s: s.get("ts_created") or s["ts_closed"])
    # COLAPSO HISTÓRICO: réplica de las guardias vivas de record() sobre lo ya guardado,
    # para que el paper account no cuente la misma idea dos veces. Dos reglas:
    #  (1) re-entrada: misma key reabierta dentro del cooldown tras cerrar → no cuenta
    #      (mismo origen que el spam DOGE; deja la 1ª y los re-tests legítimos tardíos);
    #  (2) anti-solape: mismo par+dir con zona solapada mientras otra seguía ABIERTA
    #      (concurrente) → no cuenta (mismo origen que el doble-ETH a ~1770).
    last_close, closed = {}, []
    for s in eligible:
        tcrt = s.get("ts_created") or s["ts_closed"]
        if any(a["pair"] == s["pair"] and a["dir"] == s["dir"]
               and (a.get("ts_created") or 0) <= tcrt < (a.get("ts_closed") or 0)
               and _zones_overlap(s.get("entry_lo"), s.get("entry_hi"),
                                  a.get("entry_lo"), a.get("entry_hi"))
               for a in closed):
            continue                              # (2) solape concurrente con uno ya aceptado
        cd = _REENTRY_COOLDOWN_BARS * _TF_HOURS.get(s.get("poi_tf"), 1.0) * 3600
        lc = last_close.get(s["key"])
        if lc is not None and (tcrt - lc) < cd:
            continue                              # (1) re-entrada dentro del cooldown
        closed.append(s)
        last_close[s["key"]] = s["ts_closed"]
    closed.sort(key=lambda s: s["ts_closed"])
    eq = peak = capital
    mdd = 0.0
    wins = 0
    comisiones = 0.0
    curve = []
    # Línea de tiempo del equity para poder dimensionar por el capital que había
    # al ABRIR cada operación. Los trades se recorren por cierre, pero el 99% se
    # solapa: dimensionar con el equity del cierre le presta a una operación las
    # ganancias de otras que seguían abiertas cuando ella nació (sesgo al alza,
    # medido en +16,8 puntos sobre la muestra real). Como todo trade que cerró
    # antes de que este abriera ya fue procesado, el dato está disponible.
    hitos: list[tuple[float, float]] = [(0.0, capital)]

    def _equity_al_abrir(ts_open) -> float:
        base = capital
        for ts_close, eq_tras in hitos:
            if ts_close <= (ts_open or 0):
                base = eq_tras
            else:
                break
        return base

    for s in closed:
        entry, sl = s.get("entry") or 0.0, s.get("sl") or 0.0
        slf = abs(entry - sl) / entry if entry else 0.0
        if slf <= 0:
            continue
        # Comisión round-trip sobre el NOCIONAL (costo_R = cost_frac/SL%). Maker-aware:
        # ganada = TP límite (maker), perdida = SL market (taker+slippage). Con SL
        # ajustado el nocional es grande → la comisión pesa más por trade.
        cf = _cost_fraction(s["result_r"] > 0, override=cost_rate)
        base = _equity_al_abrir(s.get("ts_created"))
        cost_usd = (cf / slf) * (risk_pct * base)
        comisiones += cost_usd
        net_r = s["result_r"] - cf / slf
        pnl = net_r * (risk_pct * base)
        eq += pnl
        hitos.append((s["ts_closed"], eq))
        if s["result_r"] > 0:
            wins += 1
        peak = max(peak, eq)
        if peak > 0:
            mdd = min(mdd, (eq - peak) / peak)
        # P&L en USD de ESTE trade (riesgo = % del equity vigente) para el registro.
        if annotate:
            s["paper_pnl" + tag] = round(pnl, 2)
            s["paper_equity" + tag] = round(eq, 2)
        curve.append({"t": s["ts_closed"], "equity": round(eq, 2)})
    # Sizing de las operaciones ABIERTAS (activas) con el equity vigente: con cuánto
    # se entró (notional), el apalancamiento efectivo y el riesgo. El P&L en vivo lo
    # calcula el frontend con el precio actual.
    # El sizing de operaciones abiertas (notional/leverage/riesgo) lo anota SOLO la
    # cuenta completa (tag==""), para no pisarlo con la base de la cuenta selectiva.
    for s in (setups if (annotate and not tag) else []):
        if s.get("status") != "activo":
            continue
        entry, sl = s.get("entry") or 0.0, s.get("sl") or 0.0
        slf = abs(entry - sl) / entry if entry else 0.0
        if slf <= 0:
            continue
        risk_usd = risk_pct * eq
        s["paper_notional"] = round(risk_usd / slf, 2)
        s["paper_leverage"] = round(risk_pct / slf, 1)
        s["paper_risk"] = round(risk_usd, 2)
        s["paper_equity_base"] = round(eq, 2)
    # ASEGURADO de trades ABIERTOS: parciales ya tomados + lo que el trailing stop
    # garantiza del runner (piso que ya no se puede perder). Se suma a la equity en
    # vivo para que la cuenta refleje las ganancias bloqueadas antes de que cierren.
    secured_open = 0.0
    open_secured_n = 0
    for s in setups:
        if s.get("status") != "activo" or not keep(s):
            continue
        entry, sl0 = s.get("entry") or 0.0, s.get("sl") or 0.0
        risk = abs(entry - sl0)
        if risk <= 0 or not entry:
            continue
        long = s["dir"] == "long"
        realized = s.get("realized_r") or 0.0
        rem = s.get("remaining")
        rem = rem if rem is not None else 0.0
        sl_cur = s.get("sl_cur")
        r_stop = 0.0
        if sl_cur is not None:
            rp = (sl_cur - entry) if long else (entry - sl_cur)
            r_stop = max(0.0, rp / risk)
        # NETO de comisiones: la comisión round-trip se pagará igual al cerrar (en
        # ganancia → salida maker).
        slf_o = risk / entry
        cf_o = _cost_fraction(True, override=cost_rate)
        net_r = realized + rem * r_stop - (cf_o / slf_o if slf_o else 0)
        if net_r > 0:
            secured_open += net_r * (risk_pct * eq)
            open_secured_n += 1
    eq_vivo = eq + secured_open
    n = len(curve)
    return {
        "capital_inicial": capital,
        "riesgo_pct": round(risk_pct * 100, 1),
        "equity": round(eq, 2),
        "asegurado_abierto": round(secured_open, 2),
        "abiertos_asegurados": open_secured_n,
        "equity_vivo": round(eq_vivo, 2),
        "comisiones": round(comisiones, 2),
        "cost_rate": round(_cost_fraction(False, override=cost_rate), 5),  # conservador (taker) para P&L de abiertos
        "pnl": round(eq - capital, 2),
        "pnl_vivo": round(eq_vivo - capital, 2),
        "return_pct": round((eq / capital - 1) * 100, 2) if capital else 0.0,
        "return_vivo_pct": round((eq_vivo / capital - 1) * 100, 2) if capital else 0.0,
        "max_dd_pct": round(mdd * 100, 1),
        "trades": n,
        "win_rate": round(wins / n * 100, 1) if n else None,
        "curve": curve[-300:],
        # El drawdown de una curva secuencial NO puede mostrar el golpe de varias
        # posiciones abiertas a la vez: aplica los trades de a uno. Estas dos
        # métricas dicen cuánto capital estuvo realmente comprometido en simultáneo
        # y cuánto de eso iba en la misma dirección (riesgo correlacionado).
        **_riesgo_simultaneo(closed, risk_pct),
    }


def _riesgo_simultaneo(closed: list, risk_pct: float) -> dict:
    """Máximo de posiciones concurrentes y % de capital en riesgo a la vez.

    Barrido de eventos apertura/cierre. `misma_dir` es el peor caso correlacionado:
    en cripto, varias posiciones del mismo lado se mueven juntas.
    """
    eventos = []
    for s in closed:
        # Comparación explícita con None: un ts_created == 0 es falsy y con `or`
        # se convertía en la hora de cierre, borrando el solape.
        abre = s.get("ts_created")
        if abre is None:
            abre = s.get("ts_closed")
        cierra = s.get("ts_closed")
        if abre is None or cierra is None:
            continue
        eventos.append((abre, 1, s.get("dir")))
        eventos.append((cierra, -1, s.get("dir")))
    if not eventos:
        return {"max_concurrentes": 0, "max_concurrentes_misma_dir": 0,
                "riesgo_simultaneo_pct": 0.0}
    eventos.sort()
    vivos = {"long": 0, "short": 0}
    peor = peor_dir = 0
    for _t, delta, direccion in eventos:
        if direccion in vivos:
            vivos[direccion] += delta
        total = vivos["long"] + vivos["short"]
        peor = max(peor, total)
        peor_dir = max(peor_dir, vivos["long"], vivos["short"])
    return {
        "max_concurrentes": peor,
        "max_concurrentes_misma_dir": peor_dir,
        "riesgo_simultaneo_pct": round(peor_dir * risk_pct * 100, 1),
    }


class SetupStore:
    """Registro con persistencia en disco y seguimiento de resultados. Thread-safe."""

    def __init__(self, path: str = SETUPS_PATH):
        self.path = path
        self._lock = threading.Lock()
        self._setups = load_all(path)

    # --- escritura (desde el loop de trading) --------------------------
    def _save(self) -> None:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._setups, fh, ensure_ascii=False)
        os.replace(tmp, self.path)

    def record(self, plan: dict, pair: str, sel_tf: str, last_price: float, now_s: float,
               source: str = "indicador") -> bool:
        """Registra un plan nuevo si no hay ya uno ABIERTO con la misma clave.
        `source`: "indicador" (auto) o "profe" (entrada manual del curso), para
        comparar después el desempeño de cada fuente. Devuelve True si creó uno."""
        if not plan:
            return False
        paper_only = bool(plan.get("paper_only"))
        k = _key(pair, plan)
        if paper_only:
            k = f"{k}:{source}"
        cooldown_s = _REENTRY_COOLDOWN_BARS * _TF_HOURS.get(plan["tf"], 1.0) * 3600
        new_lo, new_hi = plan.get("entry_lo"), plan.get("entry_hi")
        with self._lock:
            for s in self._setups:
                # GUARDIA ANTI-SOLAPE: ya hay un setup ABIERTO del mismo par y dirección
                # cuya zona se SOLAPA con la nueva → es la misma idea aunque la key difiera
                # (por centavos en el extremo, o por otra TF de POI). Abrir ambos = DOBLE
                # RIESGO sobre un mismo SL (caso ETH: dos long a ~1770, zonas casi idénticas
                # [1757,1782] vs [1758,1783], keys distintas por $1). Una sola posición por zona.
                if (s["status"] in _OPEN and s["pair"] == pair and s["dir"] == plan["dir"]
                        and bool(s.get("paper_only")) == paper_only
                        and (not paper_only or s.get("source") == source)
                        and _zones_overlap(new_lo, new_hi, s.get("entry_lo"), s.get("entry_hi"))):
                    return False
                if s["key"] != k:
                    continue
                if s["status"] in _OPEN:
                    return False  # ya lo estamos siguiendo (misma key exacta)
                # GUARDIA DE RE-ENTRADA: la misma zona cerró hace poco → todavía no se
                # re-registra (evita contar re-entradas inmediatas como trades nuevos).
                if (s["status"] in ("ganada", "perdida") and s.get("ts_closed") is not None
                        and (now_s - s["ts_closed"]) < cooldown_s):
                    return False
            entry_model = plan.get("entry_model") or ENTRY_MODEL_V2
            entry = float(plan["entry"])
            entry_tol = abs(entry) * _ZONE_BUF
            long = plan["dir"] == "long"
            at_entry = abs(float(last_price) - entry) <= entry_tol
            # Una orden límite V2 solo puede llenarse si existía antes del cruce.
            # Si el plan nace al otro lado del midpoint, queda desarmado hasta que
            # el precio vuelva al lado previo y haga un cruce nuevo.
            entry_armed = ((last_price > entry + entry_tol) if long
                           else (last_price < entry - entry_tol))
            active = (plan.get("state") == "activo" and at_entry) if entry_model == ENTRY_MODEL_V2 \
                else plan.get("state") == "activo"
            s_new = {
                "key": k,
                "source": source,
                "paper_only": paper_only,
                "strategy_tag": plan.get("strategy_tag"),
                "bta_paper": bool(plan.get("bta_paper", False)),
                "bta_reason": plan.get("bta_reason"),
                "bta_confirmed_at": (int(now_s) if plan.get("bta_paper") else None),
                "bta_rr_liq": plan.get("bta_rr_liq"),
                "ts_created": int(now_s),
                "entry_model": entry_model,
                "phase_id": (CURRENT_PHASE_ID if entry_model == ENTRY_MODEL_V2
                             else plan.get("phase_id")),
                "entry_armed": entry_armed if entry_model == ENTRY_MODEL_V2 else None,
                "activation_price": float(last_price) if active else None,
                "pair": pair,
                "sel_tf": sel_tf,
                "poi_tf": plan["tf"],
                "dir": plan["dir"],
                "entry": plan["entry"],
                "entry_lo": plan["entry_lo"],
                "entry_hi": plan["entry_hi"],
                "sl": plan["sl"],
                "tp": plan["tp"],
                "rr": plan["rr"],
                "tp_label": plan.get("tp_label", ""),
                # Disciplina premium/descuento (OTE) al generarse: para la cuenta selectiva.
                "disc_ok": plan.get("disc_ok"),
                "state_init": plan.get("state", "pendiente"),
                "scaled": bool(plan.get("scaled", False)),
                "leverage_override": plan.get("leverage_override"),
                "margin_override": plan.get("margin_override"),
                # Filtro de régimen al momento de generarse (forward-test con/sin filtro).
                "regime_ok": plan.get("regime_ok"),
                "regime_vix": plan.get("regime_vix"),
                "regime_adx": plan.get("regime_adx"),
                # CDC (cambio de carácter) como confirmación: estado al generarse y
                # cdc_ok que pasa a True si el CDC aparece mientras el setup está abierto.
                "cdc_ok": (bool(plan.get("cdc_ok"))
                           if plan.get("cdc_status") is not None else None),
                "cdc_status_init": plan.get("cdc_status"),
                "cdc_tf": plan.get("cdc_tf"),
                "cdc_t": plan.get("cdc_t"),
                "ts_cdc": None,
                "status": "activo" if active else "pendiente",
                "activated": active,
                "ts_activated": int(now_s) if active else None,
                "ts_closed": None,
                "outcome_price": None,
                "result_r": None,
                "price_at_create": last_price,
                "ts_updated": int(now_s),
            }
            self._setups.append(s_new)
            self._save()
            return s_new   # el setup creado (para graduarlo en sombra); falsy si no se creó

    def add_manual(self, pair: str, direction: str, entry: float, sl: float, tp: float,
                   tf: str = "manual", last_price: float | None = None,
                   now_s: float | None = None, label: str = "profe",
                   scaled: bool = False, leverage: float | None = None,
                   margin: float | None = None) -> dict:
        """Agrega una entrada MANUAL (del profe) al forward-test. La zona de entrada
        es el precio puntual (límite); se le sigue activación/TP/SL igual que a las
        del indicador. Devuelve {ok, created, rr, status} o {ok: False, error}."""
        try:
            entry, sl, tp = float(entry), float(sl), float(tp)
        except (TypeError, ValueError):
            return {"ok": False, "error": "entry/sl/tp deben ser números"}
        direction = "long" if str(direction).lower() in ("long", "largo", "buy", "compra") else "short"
        risk = abs(entry - sl)
        if risk <= 0 or entry <= 0:
            return {"ok": False, "error": "SL inválido (riesgo cero)"}
        # Coherencia: en long, SL<entry<TP; en short, SL>entry>TP.
        if direction == "long" and not (sl < entry < tp):
            return {"ok": False, "error": "long requiere SL < entrada < TP"}
        if direction == "short" and not (sl > entry > tp):
            return {"ok": False, "error": "short requiere SL > entrada > TP"}
        now_s = now_s or time.time()
        in_zone = last_price is not None and abs(last_price - entry) / entry <= _ZONE_BUF
        plan = {
            "tf": tf, "dir": direction, "entry": entry, "entry_lo": entry, "entry_hi": entry,
            "sl": sl, "tp": tp, "rr": round(abs(tp - entry) / risk, 2),
            "tp_label": label, "state": "activo" if in_zone else "pendiente",
            "regime_ok": None, "cdc_status": None, "scaled": scaled,
            "leverage_override": leverage, "margin_override": margin,
        }
        created = self.record(plan, pair, tf, last_price or entry, now_s, source="profe")
        return {"ok": True, "created": bool(created), "rr": plan["rr"],
                "status": plan["state"], "sl_pct": round(risk / entry * 100, 2),
                "setup": created if created else None}

    def cancel_pending(self, pair: str, direction: str, source: str | None = None,
                       near_entry: float | None = None, tol: float = 0.005) -> int:
        """Anula setups PENDIENTES del par+dirección (+fuente). Si `near_entry` se da,
        anula SOLO los cuya entrada esté a <= `tol` (0.5%) de ese precio — para reemplazar
        la entrada cercana sin tocar otras pendientes en niveles distintos."""
        n = 0
        now_s = int(time.time())
        with self._lock:
            for s in self._setups:
                if not (s.get("status") == "pendiente" and s.get("pair") == pair
                        and s.get("dir") == direction
                        and (source is None or s.get("source") == source)):
                    continue
                if near_entry is not None:
                    e = s.get("entry") or 0
                    if not e or abs(e - near_entry) / near_entry > tol:
                        continue  # entrada en otro nivel → no la tocamos
                s["status"] = "anulada"
                s["ts_closed"] = now_s
                s["ts_updated"] = now_s
                n += 1
            if n:
                self._save()
        return n

    def archive_legacy_pending(self, now_s: float | None = None) -> int:
        """Cierra solo pendientes V1 al iniciar la cohorte V2.

        Conserva todo el historial y deja los activos V1 terminar normalmente. Los
        planes V2 actuales no se tocan. Se invoca explícitamente desde el runbook de
        despliegue; nunca ocurre de manera silenciosa al importar o reiniciar.
        """
        now_s = int(now_s or time.time())
        n = 0
        with self._lock:
            for s in self._setups:
                model = s.get("entry_model") or ENTRY_MODEL_V1
                if s.get("status") != "pendiente" or model == ENTRY_MODEL_V2:
                    continue
                s["status"] = "anulada"
                s["ts_closed"] = now_s
                s["ts_updated"] = now_s
                s["close_reason"] = "phase1_v2_rollover"
                n += 1
            if n:
                self._save()
        return n

    def mark_cdc(self, pair: str, plan: dict, now_s: float) -> bool:
        """Marca cdc_ok=True en el setup ABIERTO de la misma clave: el cambio de
        carácter apareció en el POI (en la dirección correcta) mientras seguía
        abierto. Permite comparar después el desempeño con/sin confirmación."""
        k = _key(pair, plan)
        changed = False
        with self._lock:
            for s in self._setups:
                if s["key"] == k and s["status"] in _OPEN and s.get("cdc_ok") is not True:
                    s["cdc_ok"] = True
                    s["ts_cdc"] = int(now_s)
                    s["ts_updated"] = int(now_s)
                    changed = True
            if changed:
                self._save()
        return changed

    def mark_bta_paper(self, pair: str, plan: dict, now_s: float) -> bool:
        """Marca un setup normal abierto como candidato BTA paper. Se usa cuando la
        misma idea ya existe en el forward-test regular y no queremos duplicarla."""
        k = _key(pair, plan)
        changed = False
        with self._lock:
            for s in self._setups:
                if s["key"] == k and s["status"] in _OPEN and s.get("bta_paper") is not True:
                    s["bta_paper"] = True
                    s["strategy_tag"] = "bta_cdc_liq"
                    s["bta_reason"] = "POI + CDC confirmado + liquidez RR>=2"
                    s["bta_confirmed_at"] = int(now_s)
                    s["bta_rr_liq"] = plan.get("rr")
                    s["ts_updated"] = int(now_s)
                    changed = True
            if changed:
                self._save()
        return changed

    def attach_grade(self, key: str, ts_created: int, data: dict) -> bool:
        """Adjunta el GRADO de Claude (modo sombra) al setup identificado por
        key+ts_created. Se captura AL CREARSE y NO se actualiza después (registro
        prospectivo, cero look-ahead). No interviene la decisión: es solo metadata
        para validar el criterio de Claude a los ~50 trades."""
        changed = False
        with self._lock:
            for s in self._setups:
                if s["key"] == key and s.get("ts_created") == ts_created \
                        and "claude_grade" not in s:
                    s["claude_grade"] = data.get("grade")
                    s["claude_keep"] = data.get("keep")
                    s["claude_conf"] = data.get("confidence")
                    s["claude_rationale"] = data.get("rationale")
                    s["claude_graded_at"] = int(time.time())
                    changed = True
                    break
            if changed:
                self._save()
        return changed

    def protect_to_be(self, pair: str, price: float, now_s: float, reason: str = "volatilidad") -> list:
        """Defensivo (risk-off): mueve a BREAK-EVEN los trades ACTIVOS de `pair` que
        están en ganancia, para protegerlos de un evento/vela anormal. Los perdedores
        siguen con su SL. Devuelve las transiciones (para alertar)."""
        if not price:
            return []
        out = []
        with self._lock:
            changed = False
            for s in self._setups:
                if s["pair"] != pair or s["status"] != "activo":
                    continue
                long = s["dir"] == "long"
                entry = s.get("entry")
                if not entry:
                    continue
                if not ((price > entry) if long else (price < entry)):
                    continue                      # no está en ganancia → no se toca
                cur = s.get("sl_cur", s.get("sl"))
                if (cur >= entry) if long else (cur <= entry):
                    continue                      # ya en BE o mejor (trailing) → nada
                s["sl_cur"] = entry
                s["sl_be"] = True
                s["ts_updated"] = int(now_s)
                changed = True
                out.append({"type": "protect_be", "pair": pair, "dir": s["dir"],
                            "key": s["key"], "reason": reason})
            if changed:
                self._save()
        return out

    def track(self, pair: str, price: float, now_s: float) -> list:
        """Actualiza los setups ABIERTOS de un par contra el precio en vivo. Devuelve
        las TRANSICIONES ocurridas [{prev, status, ...}] para disparar alertas."""
        if not price:
            return []
        transitions = []
        trailing_live = False   # el runner en trailing mueve su stop cada poll → persistir
        state_changed = False
        with self._lock:
            for s in self._setups:
                if s["pair"] != pair or s["status"] in _CLOSED:
                    continue
                prev = s["status"]
                armed_before = s.get("entry_armed")
                for ev in self._update(s, price, now_s):
                    transitions.append({
                        "prev": prev, "status": s["status"], "pair": s["pair"],
                        "dir": s["dir"], "source": s.get("source", "indicador"),
                        "poi_tf": s.get("poi_tf"), "rr": s.get("rr"),
                        "disc_ok": s.get("disc_ok"),
                        "entry_model": s.get("entry_model") or ENTRY_MODEL_V1,
                        "phase_id": s.get("phase_id"),
                        "activation_price": s.get("activation_price"),
                        "paper_only": s.get("paper_only"),
                        "strategy_tag": s.get("strategy_tag"),
                        "bta_paper": s.get("bta_paper"),
                        "result_r": s.get("result_r"), "key": s["key"],
                        # Enriquecido para el ejecutor del bot espejo (NexUX BOT):
                        # identidad única (key+ts_created) y precios para dimensionar/cerrar.
                        "ts_created": s.get("ts_created"), "entry": s.get("entry"),
                        "sl": s.get("sl"), "tp": s.get("tp"),
                        "outcome_price": s.get("outcome_price"),
                        "realized_r": s.get("realized_r"), "remaining": s.get("remaining"),
                        "leverage_override": s.get("leverage_override"),
                        "margin_override": s.get("margin_override"),
                        **ev,   # type ("activated"|"partial"|"closed") y datos del parcial
                    })
                if s.get("entry_armed") != armed_before:
                    state_changed = True
                if s.get("trailing") and s["status"] not in _CLOSED:
                    trailing_live = True
            if transitions or trailing_live or state_changed:
                self._save()
        return transitions

    @staticmethod
    def _update(s: dict, price: float, now_s: float) -> list:
        """Avanza un setup contra el precio en vivo. Devuelve la lista de EVENTOS
        ocurridos en esta llamada: activación, parciales (TP1/TP2) con break-even, y
        cierre final. Puede haber varios en una sola llamada (gaps de precio)."""
        long = s["dir"] == "long"
        lo, hi = s["entry_lo"], s["entry_hi"]
        buf = price * _ZONE_BUF
        if not s["activated"]:
            model = s.get("entry_model") or ENTRY_MODEL_V1
            activate = False
            if model == ENTRY_MODEL_V2:
                entry = float(s.get("entry") or 0.0)
                tol = abs(entry) * _ZONE_BUF
                armed = bool(s.get("entry_armed"))
                if not armed:
                    # Re-armado causal: primero debe volver al lado desde el cual una
                    # orden límite descansaría antes de un cruce nuevo del midpoint.
                    armed = (price > entry + tol) if long else (price < entry - tol)
                    if armed:
                        s["entry_armed"] = True
                        s["ts_updated"] = int(now_s)
                if armed:
                    activate = (price <= entry + tol) if long else (price >= entry - tol)
            else:
                # Compatibilidad histórica V1: borde de zona atribuido al midpoint.
                activate = (lo - buf) <= price <= (hi + buf)
            if activate:
                s["activated"] = True
                s["status"] = "activo"
                s["ts_activated"] = int(now_s)
                s["activation_price"] = float(price)
                s["ts_updated"] = int(now_s)
                return [{"type": "activated"}]
            # Pendiente que se fue al TP sin llenarse → oportunidad perdida (anulada).
            if (long and price >= s["tp"]) or ((not long) and price <= s["tp"]):
                s["status"] = "anulada"
                s["ts_closed"] = int(now_s)
                s["outcome_price"] = price
                s["ts_updated"] = int(now_s)
                return [{"type": "closed"}]
            # Expiración por tiempo (nunca se llenó).
            exp_h = _EXPIRE_HOURS.get(s["poi_tf"], _DEFAULT_EXPIRE_H)
            if now_s - s["ts_created"] > exp_h * 3600:
                s["status"] = "anulada"
                s["ts_closed"] = int(now_s)
                s["ts_updated"] = int(now_s)
                return [{"type": "closed"}]
            return []

        # Entradas MANUALES (profe): se siguen TAL CUAL su plan — TP o SL completo,
        # SIN parciales ni break-even. La idea del forward-test del profe es comparar
        # SU gestión (aguantar a TP/SL, SL ancho) contra la nuestra (SMC escalonada);
        # aplicarle nuestras parciales lo cerraba antes de tiempo en break-even.
        if (s.get("sel_tf") == "manual" or s.get("source") == "profe"
                or s.get("paper_only")) and not s.get("scaled"):
            return SetupStore._update_simple(s, price, now_s)

        # --- Activo: plan de salida ESCALONADA (parciales) + break-even ---
        entry, sl0, rr = s["entry"], s["sl"], float(s["rr"])
        risk = abs(entry - sl0)
        if risk <= 0:                       # plan degenerado → resolución simple
            return SetupStore._update_simple(s, price, now_s)
        # Estado de parciales (init perezoso para trades ya abiertos antes del deploy).
        if "remaining" not in s:
            s["remaining"] = 1.0
            s["realized_r"] = 0.0
            s["legs_filled"] = 0
            s["sl_cur"] = sl0
            s["sl_be"] = False
        events = []
        # 1) Stop / break-even primero (conservador). En BE el SL = entrada → aporta 0R.
        if (long and price <= s["sl_cur"]) or ((not long) and price >= s["sl_cur"]):
            stop_r = (s["sl_cur"] - entry) / risk if long else (entry - s["sl_cur"]) / risk
            s["realized_r"] = round(s["realized_r"] + s["remaining"] * stop_r, 4)
            s["remaining"] = 0.0
            s["result_r"] = s["realized_r"]
            s["status"] = "ganada" if s["result_r"] > 1e-9 else "perdida"
            s["outcome_price"] = s["sl_cur"]
            s["ts_closed"] = int(now_s)
            s["ts_updated"] = int(now_s)
            return [{"type": "closed", "be": s.get("sl_be", False)}]
        # 2) Parciales intermedios (TP1, TP2…) en orden.
        for idx, (R, frac) in enumerate(PARTIAL_LEGS):
            if s["legs_filled"] > idx:
                continue                    # ya tomado
            if R >= rr:
                break                       # cae en/más allá del TP lejano → lo cubre el runner
            target = entry + R * risk if long else entry - R * risk
            if (long and price >= target) or ((not long) and price <= target):
                s["realized_r"] = round(s["realized_r"] + frac * R, 4)
                s["remaining"] = round(s["remaining"] - frac, 4)
                s["legs_filled"] = idx + 1
                if s["legs_filled"] >= PARTIAL_BE_AFTER and not s["sl_be"]:
                    s["sl_cur"] = entry      # SL a break-even
                    s["sl_be"] = True
                events.append({"type": "partial", "leg": _LEG_NAMES.get(idx, f"TP{idx+1}"),
                               "r_level": R, "frac_closed": frac,
                               "realized_r": s["realized_r"], "remaining": s["remaining"],
                               "be": s["sl_be"]})
            else:
                break                        # legs en orden: si no llegó, los siguientes tampoco
        # 3) Runner con TRAILING STOP: tras llenar todos los parciales, el último tramo
        # NO va a un TP fijo; se deja correr asegurando con un stop que sigue al precio a
        # PARTIAL_TRAIL_R de distancia (nunca peor que break-even). El backtest mostró que
        # esto rinde +20% vs el TP fijo, con el mismo drawdown.
        n_active = sum(1 for (R, _) in PARTIAL_LEGS if R < rr)   # legs que no absorbe el runner
        if s["remaining"] > 1e-9 and s["legs_filled"] >= n_active:
            td = PARTIAL_TRAIL_R * risk
            if not s.get("trailing"):
                s["trailing"] = True
                s["trail_best"] = price            # mejor precio a favor al iniciar
            if long:
                s["trail_best"] = max(s["trail_best"], price)
                s["sl_cur"] = max(s["sl_cur"], s["trail_best"] - td)
            else:
                s["trail_best"] = min(s["trail_best"], price)
                s["sl_cur"] = min(s["sl_cur"], s["trail_best"] + td)
            # ¿el precio retrocedió hasta el trailing stop? → cierre del runner.
            if (long and price <= s["sl_cur"]) or ((not long) and price >= s["sl_cur"]):
                stop_r = (s["sl_cur"] - entry) / risk if long else (entry - s["sl_cur"]) / risk
                s["realized_r"] = round(s["realized_r"] + s["remaining"] * stop_r, 4)
                s["remaining"] = 0.0
                s["result_r"] = s["realized_r"]
                s["status"] = "ganada" if s["result_r"] > 1e-9 else "perdida"
                s["outcome_price"] = s["sl_cur"]
                s["ts_closed"] = int(now_s)
                events.append({"type": "closed", "be": True, "trail": True})
        if events:
            s["ts_updated"] = int(now_s)
        return events

    @staticmethod
    def _update_simple(s: dict, price: float, now_s: float) -> list:
        """Resolución binaria (respaldo si no hay distancia de SL válida)."""
        long = s["dir"] == "long"
        if (long and price <= s["sl"]) or ((not long) and price >= s["sl"]):
            s["status"] = "perdida"; s["result_r"] = -1.0; s["outcome_price"] = s["sl"]
        elif (long and price >= s["tp"]) or ((not long) and price <= s["tp"]):
            s["status"] = "ganada"; s["result_r"] = float(s["rr"]); s["outcome_price"] = s["tp"]
        else:
            return []
        s["ts_closed"] = int(now_s); s["ts_updated"] = int(now_s)
        return [{"type": "closed"}]

    # --- lectura -------------------------------------------------------
    def all(self) -> list:
        with self._lock:
            return list(self._setups)
