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
en el Mac mini, donde el autostart corre Nexux de forma continua)."""
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

_OPEN = ("pendiente", "activo")
_CLOSED = ("ganada", "perdida", "anulada")


def _key(pair: str, plan: dict) -> str:
    """Clave de deduplicación: par + TF del POI + dirección + extremo de la zona."""
    return f"{pair}:{plan['tf']}:{plan['dir']}:{round(plan['entry_lo'], 2)}"


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
    return out


# --- Cuenta PAPER (forward-test con dinero simulado) -----------------------
# Convierte los setups cerrados en P&L en USD con sizing por riesgo, compuesto.
# Es la config que el estudio nocturno marcó como sana (ver
# research/veredicto_estrategia_2026-06-13.md): ~2% de riesgo por trade (≈3x
# efectivo con el SL ajustado), NO 10x/20x. Dinero SIMULADO: valida la ejecución
# antes de arriesgar real.
PAPER_CAPITAL = 38000.0     # capital inicial (USD) — el de Hugo en Binance
PAPER_RISK_PCT = 0.02       # riesgo por trade (2% del capital, compuesto)
PAPER_COST_RATE = 0.0014    # comisión 0.05%/lado + slippage 0.02%/fill (round-trip)


# Cuenta SELECTIVA = la config ÓPTIMA del laboratorio (validada IS/OOS): zona POI de
# timeframe ALTO (4h/1D) + disciplina premium/descuento (OTE) + R:R ≥ 5. Es el edge
# más fuerte (avgR ~0,92, win 85%, PF 7,3). La cuenta completa registra todo en
# paralelo, para comparar calidad vs cantidad y tomar decisiones a futuro.
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
                  cost_rate: float = PAPER_COST_RATE,
                  selector=None, annotate: bool = True) -> dict:
    """Cuenta de PAPER TRADING sobre los setups CERRADOS (ganada/perdida): cada
    trade arriesga `risk_pct` del capital vigente (compuesto); el P&L en USD es
    R_neto × riesgo, con R_neto = result_r − costo (costo_R = cost_rate / SL%).
    Devuelve equity final, P&L, retorno %, drawdown máximo y la curva. Es dinero
    simulado — el bot NO coloca órdenes.

    `selector`: si se da, solo cuenta los setups que lo cumplen (cuenta selectiva).
    `annotate`: si False, no escribe paper_* en los setups (para no pisar la cuenta
    completa cuando se calcula una segunda cuenta filtrada)."""
    keep = selector or (lambda s: True)
    closed = sorted(
        [s for s in setups
         if s["status"] in ("ganada", "perdida")
         and s.get("result_r") is not None and s.get("ts_closed") and keep(s)],
        key=lambda s: s["ts_closed"])
    eq = peak = capital
    mdd = 0.0
    wins = 0
    curve = []
    for s in closed:
        entry, sl = s.get("entry") or 0.0, s.get("sl") or 0.0
        slf = abs(entry - sl) / entry if entry else 0.0
        if slf <= 0:
            continue
        net_r = s["result_r"] - cost_rate / slf
        pnl = net_r * (risk_pct * eq)
        eq += pnl
        if s["result_r"] > 0:
            wins += 1
        peak = max(peak, eq)
        if peak > 0:
            mdd = min(mdd, (eq - peak) / peak)
        # P&L en USD de ESTE trade (riesgo = % del equity vigente) para el registro.
        if annotate:
            s["paper_pnl"] = round(pnl, 2)
            s["paper_equity"] = round(eq, 2)
        curve.append({"t": s["ts_closed"], "equity": round(eq, 2)})
    # Sizing de las operaciones ABIERTAS (activas) con el equity vigente: con cuánto
    # se entró (notional), el apalancamiento efectivo y el riesgo. El P&L en vivo lo
    # calcula el frontend con el precio actual.
    for s in setups if annotate else []:
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
    n = len(curve)
    return {
        "capital_inicial": capital,
        "riesgo_pct": round(risk_pct * 100, 1),
        "equity": round(eq, 2),
        "pnl": round(eq - capital, 2),
        "return_pct": round((eq / capital - 1) * 100, 2) if capital else 0.0,
        "max_dd_pct": round(mdd * 100, 1),
        "trades": n,
        "win_rate": round(wins / n * 100, 1) if n else None,
        "curve": curve[-300:],
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
        k = _key(pair, plan)
        with self._lock:
            for s in self._setups:
                if s["key"] == k and s["status"] in _OPEN:
                    return False  # ya lo estamos siguiendo
            active = plan.get("state") == "activo"
            self._setups.append({
                "key": k,
                "source": source,
                "ts_created": int(now_s),
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
                "ts_cdc": None,
                "status": "activo" if active else "pendiente",
                "activated": active,
                "ts_activated": int(now_s) if active else None,
                "ts_closed": None,
                "outcome_price": None,
                "result_r": None,
                "price_at_create": last_price,
                "ts_updated": int(now_s),
            })
            self._save()
            return True

    def add_manual(self, pair: str, direction: str, entry: float, sl: float, tp: float,
                   tf: str = "manual", last_price: float | None = None,
                   now_s: float | None = None, label: str = "profe") -> dict:
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
            "regime_ok": None, "cdc_status": None,
        }
        created = self.record(plan, pair, tf, last_price or entry, now_s, source="profe")
        return {"ok": True, "created": created, "rr": plan["rr"],
                "status": plan["state"], "sl_pct": round(risk / entry * 100, 2)}

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

    def track(self, pair: str, price: float, now_s: float) -> list:
        """Actualiza los setups ABIERTOS de un par contra el precio en vivo. Devuelve
        las TRANSICIONES ocurridas [{prev, status, ...}] para disparar alertas."""
        if not price:
            return []
        transitions = []
        trailing_live = False   # el runner en trailing mueve su stop cada poll → persistir
        with self._lock:
            for s in self._setups:
                if s["pair"] != pair or s["status"] in _CLOSED:
                    continue
                prev = s["status"]
                for ev in self._update(s, price, now_s):
                    transitions.append({
                        "prev": prev, "status": s["status"], "pair": s["pair"],
                        "dir": s["dir"], "source": s.get("source", "indicador"),
                        "poi_tf": s.get("poi_tf"), "rr": s.get("rr"),
                        "result_r": s.get("result_r"), "key": s["key"],
                        **ev,   # type ("activated"|"partial"|"closed") y datos del parcial
                    })
                if s.get("trailing") and s["status"] not in _CLOSED:
                    trailing_live = True
            if transitions or trailing_live:
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
            # ¿el precio entró a la zona del POI? → se activa la entrada.
            if (lo - buf) <= price <= (hi + buf):
                s["activated"] = True
                s["status"] = "activo"
                s["ts_activated"] = int(now_s)
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
