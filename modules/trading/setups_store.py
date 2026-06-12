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
    return out


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

    def record(self, plan: dict, pair: str, sel_tf: str, last_price: float, now_s: float) -> bool:
        """Registra un plan nuevo si no hay ya uno ABIERTO con la misma clave.
        Devuelve True si creó un registro."""
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

    def track(self, pair: str, price: float, now_s: float) -> bool:
        """Actualiza los setups ABIERTOS de un par contra el precio en vivo."""
        if not price:
            return False
        changed = False
        with self._lock:
            for s in self._setups:
                if s["pair"] != pair or s["status"] in _CLOSED:
                    continue
                if self._update(s, price, now_s):
                    changed = True
            if changed:
                self._save()
        return changed

    @staticmethod
    def _update(s: dict, price: float, now_s: float) -> bool:
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
                return True
            # Pendiente que se fue al TP sin llenarse → oportunidad perdida (anulada).
            if (long and price >= s["tp"]) or ((not long) and price <= s["tp"]):
                s["status"] = "anulada"
                s["ts_closed"] = int(now_s)
                s["outcome_price"] = price
                s["ts_updated"] = int(now_s)
                return True
            # Expiración por tiempo (nunca se llenó).
            exp_h = _EXPIRE_HOURS.get(s["poi_tf"], _DEFAULT_EXPIRE_H)
            if now_s - s["ts_created"] > exp_h * 3600:
                s["status"] = "anulada"
                s["ts_closed"] = int(now_s)
                s["ts_updated"] = int(now_s)
                return True
            return False
        # Activo: resolver TP / SL.
        if long:
            hit_sl = price <= s["sl"]
            hit_tp = price >= s["tp"]
        else:
            hit_sl = price >= s["sl"]
            hit_tp = price <= s["tp"]
        if hit_sl:
            s["status"] = "perdida"
            s["result_r"] = -1.0
            s["outcome_price"] = s["sl"]
        elif hit_tp:
            s["status"] = "ganada"
            s["result_r"] = float(s["rr"])
            s["outcome_price"] = s["tp"]
        else:
            return False
        s["ts_closed"] = int(now_s)
        s["ts_updated"] = int(now_s)
        return True

    # --- lectura -------------------------------------------------------
    def all(self) -> list:
        with self._lock:
            return list(self._setups)
