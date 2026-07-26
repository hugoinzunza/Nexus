"""Acción del precio — cálculo puro, sin red y sin estado.

Traduce a datos los conceptos del curso CreceTrader (apuntes en
`research/crecetrader/`) que tienen una definición OBJETIVA. Lo que en el curso es
lectura visual —numerar fases I-V, trazar una directriz a mano, elegir qué fase
histórica ancla los refugios de largo plazo— NO está acá y no debe agregarse: son
decisiones que dependen de qué extremos eligió el ojo, y el propio material admite
que cambiando los extremos la misma vela rompe o no rompe.

Nada de este archivo es una señal. Ninguna función decide entrar ni salir. Todo lo
que devuelve va a pantalla marcado como research sin validar.

REGLA DE CAUSALIDAD, que es la que da valor a todo lo demás: un pivote solo existe
después de sus barras de la derecha. `swing_points` de `modules.trading.smc` ya
devuelve `confirm_idx` justamente por eso, y acá se respeta sin excepción. Fechar un
pivote en su extremo en vez de en su confirmación es look-ahead, y es el error más
caro que cometimos en este proyecto: un bucle que arrancaba una vela antes costaba
1,5R por trade.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from modules.trading import smc

# Paso de la rejilla anual. El curso usa 10% y lo presenta como un número con
# significado; no lo tiene demostrado. Queda como constante VISIBLE y con placebos
# declarados al lado para que la pantalla nunca sugiera que el 10% es especial.
PASO_RMP = 0.10
PASOS_PLACEBO = (0.075, 0.125)

# Hasta dónde extender la rejilla. El tope es 9 A PROPÓSITO: con `k = 10` hacia abajo
# la fórmula del curso da precio CERO, y más allá negativo, que no significa nada para
# un activo. El apunte lo marca como algo que "una implementación debe descartar
# explícitamente"; acá se descarta eligiendo el tope, no filtrando después. El guardia
# de `precio <= 0` en `rejilla()` es por si alguien sube este número, y con K_MAX=9
# nunca dispara.
K_MAX = 9


def apertura_anual(velas_diarias: list[dict], anio: int) -> Optional[dict]:
    """Apertura de la primera vela diaria del año `anio`.

    Es el ancla de los refugios de mediano plazo. A diferencia de casi todo lo demás
    del curso, este número es un HECHO HISTÓRICO: el 1 de enero ya pasó y no cambia
    aunque los datos estén viejos. Por eso la rejilla anual se puede publicar sin
    depender de la frescura del dataset.

    Devuelve None si el año no tiene datos desde su comienzo. No se inventa el ancla
    con la primera vela que haya: si el par se listó en marzo, su "apertura anual" de
    ese año sería una ficción con cara de dato.
    """
    inicio = dt.datetime(anio, 1, 1, tzinfo=dt.timezone.utc)
    fin = dt.datetime(anio, 1, 3, tzinfo=dt.timezone.utc)   # margen de 2 días
    ini_ms, fin_ms = int(inicio.timestamp() * 1000), int(fin.timestamp() * 1000)
    for v in velas_diarias:
        t = int(v["t"])
        if ini_ms <= t < fin_ms:
            return {"t": t, "precio": float(v["o"]),
                    "fecha": dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc)
                              .strftime("%Y-%m-%d")}
    return None


def apertura_semanal(velas: list[dict], ahora_ms: int) -> Optional[dict]:
    """Apertura de la semana en curso (lunes 00:00 UTC).

    El curso la usa como referencia de sesgo intradía. Acá se fija UTC de forma
    explícita: los ejemplos del curso usan la semana de Londres, que cambia con el
    horario de verano mientras UTC no, y mezclarlas en silencio produce dos aperturas
    distintas para la misma semana.

    A diferencia de la apertura anual, ESTA sí envejece: si el dataset no llega a la
    semana en curso, devuelve None en vez de entregar la de una semana vieja
    disfrazada de actual.
    """
    ahora = dt.datetime.fromtimestamp(ahora_ms / 1000, dt.timezone.utc)
    lunes = (ahora - dt.timedelta(days=ahora.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0)
    ini_ms = int(lunes.timestamp() * 1000)
    candidatas = [v for v in velas if int(v["t"]) >= ini_ms]
    if not candidatas:
        return None
    primera = min(candidatas, key=lambda v: int(v["t"]))
    return {"t": int(primera["t"]), "precio": float(primera["o"]),
            "fecha": lunes.strftime("%Y-%m-%d")}


def rejilla(ancla: float, precio: float, paso: float = PASO_RMP,
            k_max: int = K_MAX) -> list[dict]:
    """Niveles `ancla * (1 ± k*paso)`, con la distancia al precio de hoy.

    Los pasos son LINEALES respecto del ancla, no compuestos: +20% es `ancla*1.20`,
    no `ancla*1.10^2`. El apunte lo confirma contra la planilla del curso, y es fácil
    equivocarse porque la intuición financiera dice lo contrario.

    Se excluyen los niveles con precio <= 0 (`k >= 10` hacia abajo). Salen igual en el
    conteo de descartados para que la pantalla pueda decir cuántos se cayeron, en vez
    de que desaparezcan sin dejar rastro.
    """
    filas, descartados = [], 0
    for k in range(1, k_max + 1):
        for signo in (1, -1):
            px = ancla * (1 + signo * k * paso)
            if px <= 0:
                descartados += 1
                continue
            filas.append({
                "k": k, "dir": "arriba" if signo > 0 else "abajo",
                "pct_del_ancla": round(signo * k * paso * 100, 1),
                "precio": px,
                "dist_pct": round((px / precio - 1) * 100, 2) if precio else None,
            })
    filas.sort(key=lambda f: f["precio"])
    for f in filas:
        f["descartados_por_precio_no_positivo"] = descartados
    return filas


def estructura(velas: list[dict], piv: int, as_of_idx: Optional[int] = None) -> dict:
    """Pivotes confirmados y estructura, tal como los vería alguien en `as_of_idx`.

    `piv` es la mitad de la ventana: el curso enseña 5+1+5, o sea `piv=5`. No se toma
    ese 5 como verdad — NexUX ya usa 10 para rangos y 2 para el CDC, y la
    justificación del curso (cinco días bursátiles de una semana) no traslada a cripto
    24/7. Queda como parámetro y la pantalla muestra cuál se usó.

    Un pivote entra solo si `confirm_idx <= as_of_idx`. Sin eso, la "estructura"
    incluiría extremos que todavía no eran extremos, que es la forma más común de
    hacer trampa sin darse cuenta.
    """
    if not velas or len(velas) < 2 * piv + 3:
        return {"piv": piv, "highs": [], "lows": [], "tendencia": "sin_datos",
                "motivo": f"hacen falta al menos {2 * piv + 3} velas"}
    tope = len(velas) - 1 if as_of_idx is None else as_of_idx
    highs, lows = smc.swing_points(velas, piv)
    hs = [p for p in highs if p["confirm_idx"] <= tope]
    ls = [p for p in lows if p["confirm_idx"] <= tope]

    # Tendencia por los DOS últimos pivotes de cada lado. Dos no es un número mágico:
    # es el mínimo para hablar de "creciente" y el máximo que se puede exigir sin
    # inventar una regla que el curso no da. Con menos de dos, se dice "indefinida" en
    # vez de forzar una lectura.
    tendencia = "indefinida"
    if len(hs) >= 2 and len(ls) >= 2:
        hh = hs[-1]["price"] > hs[-2]["price"]
        hl = ls[-1]["price"] > ls[-2]["price"]
        lh = hs[-1]["price"] < hs[-2]["price"]
        ll = ls[-1]["price"] < ls[-2]["price"]
        if hh and hl:
            tendencia = "alcista"
        elif lh and ll:
            tendencia = "bajista"
        else:
            tendencia = "lateral"
    return {"piv": piv, "highs": hs[-6:], "lows": ls[-6:], "tendencia": tendencia,
            "n_highs": len(hs), "n_lows": len(ls),
            "retraso_velas": piv}


def vacio_disponible(precio: float, direccion: str, sl: float,
                     referencias: list[dict]) -> dict:
    """Distancia al PRIMER obstáculo, y cuántos hay antes de un objetivo lejano.

    Es la única idea del curso que NexUX no tenía. El TP del bot
    (`smc_live._opposite_liquidity`) toma la liquidez weak más cercana y NO cuenta
    como obstáculo los niveles strong intermedios, los POIs de otras temporalidades
    ni la liquidez del lado contrario. Un RR alto medido a través de tres paredes es
    aritméticamente correcto y operativamente ilusorio.

    `referencias` son dicts con al menos `precio`; opcionalmente `tipo` y `tf`. El
    llamador decide qué cuenta como referencia — esta función no elige por él, porque
    "cuál es el primer obstáculo" elegido después de ver el recorrido es exactamente
    la trampa que el concepto viene a denunciar.

    OJO con el alcance: esto NO explica la brecha entre el backtest (67,4% llega a
    TP1) y el Diario real (33,3%), porque ambos usan el mismo cálculo de TP y una
    ceguera compartida no produce divergencia. Lo que pone en duda es la coherencia
    del gate rr>=5, que es otra cosa.
    """
    largo = direccion == "long"
    adelante = [r for r in referencias
                if (float(r["precio"]) > precio if largo
                    else float(r["precio"]) < precio)]
    if not adelante:
        return {"primer_obstaculo": None, "vacuum_rr": None, "n_adelante": 0,
                "nota": "no hay referencias conocidas en la dirección del trade"}
    primero = min(adelante, key=lambda r: abs(float(r["precio"]) - precio))
    riesgo = abs(precio - sl)
    return {
        "primer_obstaculo": primero,
        "distancia_pct": round((float(primero["precio"]) / precio - 1) * 100, 2),
        "vacuum_rr": round(abs(float(primero["precio"]) - precio) / riesgo, 2)
                     if riesgo > 0 else None,
        "n_adelante": len(adelante),
    }


def obstaculos_entre(entry: float, target: float, direccion: str,
                     referencias: list[dict]) -> dict:
    """Cuántas referencias hay ESTRICTAMENTE entre la entrada y el objetivo.

    `obstacle_count > 0` significa que el RR planificado se mide atravesando algo.
    No dice que el trade sea malo —eso lo tiene que decidir un estudio, no una
    pantalla— pero sí que el número que aparece como RR no es el recorrido libre.
    """
    largo = direccion == "long"
    lo, hi = (entry, target) if largo else (target, entry)
    dentro = [r for r in referencias if lo < float(r["precio"]) < hi]
    dentro.sort(key=lambda r: abs(float(r["precio"]) - entry))
    return {"obstacle_count": len(dentro), "obstaculos": dentro[:8],
            "target_atraviesa_referencias": len(dentro) > 0}
