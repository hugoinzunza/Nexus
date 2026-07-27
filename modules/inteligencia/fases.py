"""Fases causales del modelo CreceTrader.

Una fase se publica cuando el pivote que la termina ya fue confirmado. El trazo
puede comenzar en el extremo histórico, pero `available_at` declara cuándo pudo
conocerlo un observador real. No se renumeran fases antiguas al llegar datos nuevos.
"""
from __future__ import annotations

from modules.trading import smc
from . import precio as P


def pivotes_confirmados(velas: list[dict], tf: str, piv: int = 5) -> dict:
    if len(velas) < 2 * piv + 3:
        return {"highs": [], "lows": [], "eventos": []}
    highs, lows = smc.swing_points(velas, piv)
    paso = P.TF_MS[tf]

    def enriquecer(punto: dict, tipo: str) -> dict:
        return {
            **punto,
            "tipo": tipo,
            "pivot_t": int(velas[punto["idx"]]["t"]),
            "confirmed_at": int(velas[punto["confirm_idx"]]["t"]) + paso,
        }

    hs = [enriquecer(p, "high") for p in highs]
    ls = [enriquecer(p, "low") for p in lows]
    dobles = {p["idx"] for p in hs} & {p["idx"] for p in ls}
    hs = [p for p in hs if p["idx"] not in dobles]
    ls = [p for p in ls if p["idx"] not in dobles]
    eventos = sorted(hs + ls, key=lambda p: (p["confirm_idx"], p["idx"], p["tipo"]))
    return {"highs": hs, "lows": ls, "eventos": eventos}


def ciclos_confirmados(velas: list[dict], tf: str, piv: int = 5,
                       correction_min: float = 0.382,
                       correction_max: float = 0.618) -> list[dict]:
    """Emite I->II cuando el tercer pivote queda disponible.

    La secuencia se construye por orden de confirmación, no sobre el zigzag final.
    Así un extremo más profundo que aparece después puede crear una candidata nueva,
    pero nunca borrar la que un observador ya había visto.
    """
    puntos = pivotes_confirmados(velas, tf, piv)
    secuencia = []
    emitidos = set()
    ciclos = []

    for punto in puntos["eventos"]:
        if not secuencia or secuencia[-1]["tipo"] != punto["tipo"]:
            secuencia.append(punto)
        else:
            anterior = secuencia[-1]
            mas_extremo = (punto["price"] > anterior["price"]
                           if punto["tipo"] == "high"
                           else punto["price"] < anterior["price"])
            if mas_extremo:
                secuencia[-1] = punto
            else:
                continue
        if len(secuencia) < 3:
            continue
        a, b, c = secuencia[-3:]
        patron_long = (a["tipo"], b["tipo"], c["tipo"]) == ("low", "high", "low")
        patron_short = (a["tipo"], b["tipo"], c["tipo"]) == ("high", "low", "high")
        if not (patron_long or patron_short):
            continue
        recorrido = abs(float(b["price"]) - float(a["price"]))
        if recorrido <= 0:
            continue
        retroceso = abs(float(b["price"]) - float(c["price"])) / recorrido
        conserva_origen = (c["price"] > a["price"] if patron_long
                           else c["price"] < a["price"])
        if not conserva_origen or not correction_min <= retroceso <= correction_max:
            continue
        clave = (a["idx"], b["idx"], c["idx"])
        if clave in emitidos:
            continue
        emitidos.add(clave)
        side = "long" if patron_long else "short"
        ciclos.append({
            "id": f"{tf}:{side}:{a['idx']}:{b['idx']}:{c['idx']}",
            "tf": tf,
            "side": side,
            "piv": piv,
            "retroceso": round(retroceso, 6),
            "available_idx": max(a["confirm_idx"], b["confirm_idx"], c["confirm_idx"]),
            "available_at": max(a["confirmed_at"], b["confirmed_at"], c["confirmed_at"]),
            "phase_i": {
                "label": "I",
                "start_idx": a["idx"], "end_idx": b["idx"],
                "start_t": a["pivot_t"], "end_t": b["pivot_t"],
                "start_price": float(a["price"]), "end_price": float(b["price"]),
                "available_at": b["confirmed_at"],
            },
            "phase_ii": {
                "label": "II",
                "start_idx": b["idx"], "end_idx": c["idx"],
                "start_t": b["pivot_t"], "end_t": c["pivot_t"],
                "start_price": float(b["price"]), "end_price": float(c["price"]),
                "available_at": c["confirmed_at"],
            },
            "origin": a,
            "impulse_end": b,
            "correction_end": c,
        })
    return ciclos


def fases_para_grafico(velas: list[dict], tf: str, piv: int = 5,
                       limit: int = 8) -> list[dict]:
    ciclos = ciclos_confirmados(velas, tf, piv)
    salida = []
    visibles = ciclos[-limit:]
    for pos, ciclo in enumerate(visibles):
        phase_iii = None
        status = "I-II confirmadas"
        # La III no se declara terminada retrospectivamente. Solo el ciclo más
        # reciente conserva un tramo candidato desde la corrección hasta la última
        # vela cerrada, siempre que el origen estructural siga vigente.
        if pos == len(visibles) - 1 and velas:
            ultimo = velas[-1]
            origen = float(ciclo["origin"]["price"])
            posteriores = velas[ciclo["available_idx"] + 1:]
            vigente = (all(float(v["l"]) > origen for v in posteriores)
                       if ciclo["side"] == "long"
                       else all(float(v["h"]) < origen for v in posteriores))
            if vigente:
                phase_iii = {
                    "label": "III?",
                    "start_idx": ciclo["correction_end"]["idx"],
                    "end_idx": len(velas) - 1,
                    "start_t": ciclo["correction_end"]["pivot_t"],
                    "end_t": int(ultimo["t"]),
                    "start_price": float(ciclo["correction_end"]["price"]),
                    "end_price": float(ultimo["c"]),
                    "available_at": ciclo["available_at"],
                    "candidate": True,
                }
                status = "III candidata"
        salida.append({
            "id": ciclo["id"],
            "side": ciclo["side"],
            "retroceso": ciclo["retroceso"],
            "available_at": ciclo["available_at"],
            "segments": [ciclo["phase_i"], ciclo["phase_ii"]],
            "phase_iii": phase_iii,
            "status": status,
        })
    return salida
