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

# El estudio pre-registrado y la hoja del profesor usan k=1..15. Hacia abajo, los
# niveles que llegan a cero o negativo se descartan; hacia arriba esto conserva +150%.
K_MAX = 15

TF_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
    "1w": 604_800_000,
}

# 0.236 aparece explícitamente en el taller y en la plantilla RLP. 0.812 no entra:
# la propia transcripción dice que podría ser 0.786 u otro valor y el profesor suele
# ocultarlo. Una cifra ambigua no puede convertirse en línea automática.
RETROCESOS = (0.236, 0.382, 0.40, 0.50, 0.60, 0.618)
EXTENSIONES = (1.25, 1.50, 1.618, 2.00)

# Inventario de la familia RLP descrita en el curso. La fórmula es exacta; el ancla
# histórica L/H no lo es. Se publica para declarar qué falta, no para aplicarla a una
# pierna elegida retrospectivamente.
RLP_RATIOS_DOCUMENTADOS = (
    0.0, 0.236, 0.382, 0.5, 0.618, 1.0, 1.236, 1.5, 1.618,
    2.0, 2.618, 4.236, 6.854, 11.09,
)
RLP_RATIOS_AMBIGUOS = (0.812,)


def velas_cerradas(velas: list[dict], tf: str, as_of_ms: int) -> list[dict]:
    """Solo barras cuyo cierre ya existía en `as_of_ms`.

    Binance incluye la barra en formación. Usarla como quinta vela derecha permite
    confirmar un pivote que todavía puede desaparecer antes del cierre.
    """
    paso = TF_MS[tf]
    return [v for v in velas if int(v["t"]) + paso <= as_of_ms]


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
    ini_ms = int(inicio.timestamp() * 1000)
    for v in velas_diarias:
        t = int(v["t"])
        if t == ini_ms:
            return {"t": t, "precio": float(v["o"]),
                    "fecha": dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc)
                              .strftime("%Y-%m-%d")}
    return None


def aperturas_anuales(velas_diarias: list[dict]) -> list[dict]:
    """Aperturas exactas del 1 de enero presentes en el histórico.

    No conserva retrospectivamente solo las que reaccionaron: devuelve todo año cuyo
    ancla exacta existe en la serie. Esa diferencia permite mostrar contexto histórico
    sin copiar la selección discrecional de "refugios exitosos" del curso.
    """
    resultado = []
    for v in velas_diarias:
        t = int(v["t"])
        fecha = dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc)
        if (fecha.month, fecha.day, fecha.hour, fecha.minute) != (1, 1, 0, 0):
            continue
        resultado.append({
            "anio": fecha.year,
            "t": t,
            "precio": float(v["o"]),
            "fecha": fecha.strftime("%Y-%m-%d"),
        })
    return resultado


def apertura_semanal(velas: list[dict], ahora_ms: int) -> Optional[dict]:
    """Apertura de la semana en curso (lunes 00:00 UTC).

    El curso la usa como referencia de sesgo intradía. Acá se fija UTC de forma
    explícita: los ejemplos del curso usan la semana de Londres, que cambia con el
    horario de verano mientras UTC no, y mezclarlas en silencio produce dos aperturas
    distintas para la misma semana.

    A diferencia de la apertura anual, ESTA sí envejece: si el dataset no llega a la
    semana en curso, devuelve None en vez de entregar la de una semana vieja
    disfrazada de actual.

    Puede recibir la vela de 1h todavía abierta: su OHLC final no existe, pero su
    apertura quedó fijada en el instante en que comenzó la semana.
    """
    ahora = dt.datetime.fromtimestamp(ahora_ms / 1000, dt.timezone.utc)
    lunes = (ahora - dt.timedelta(days=ahora.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0)
    ini_ms = int(lunes.timestamp() * 1000)
    exacta = next((v for v in velas if int(v["t"]) == ini_ms), None)
    if exacta is None:
        return None
    return {"t": int(exacta["t"]), "precio": float(exacta["o"]),
            "fecha": lunes.strftime("%Y-%m-%d")}


def rejilla(ancla: float, precio: float, paso: float = PASO_RMP,
            k_max: int = K_MAX) -> list[dict]:
    """Niveles `ancla * (1 ± k*paso)`, con la distancia al precio de hoy.

    Los pasos son LINEALES respecto del ancla, no compuestos: +20% es `ancla*1.20`,
    no `ancla*1.10^2`. El apunte lo confirma contra la planilla del curso, y es fácil
    equivocarse porque la intuición financiera dice lo contrario.

    `k_max` también se conserva igual en los placebos: esa fue la especificación
    pre-registrada del estudio cuyos resultados muestra la interfaz. Cambiar el rango
    visible de un placebo sin recalcular sus métricas mezclaría dos experimentos.
    """
    filas = []
    for signo in (1, -1):
        for k in range(1, k_max + 1):
            px = ancla * (1 + signo * k * paso)
            if px <= 0:
                continue
            filas.append({
                "k": k, "dir": "arriba" if signo > 0 else "abajo",
                "pct_del_ancla": round(signo * k * paso * 100, 1),
                "precio": px,
                "dist_pct": round((px / precio - 1) * 100, 2) if precio else None,
            })
    filas.sort(key=lambda f: f["precio"])
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
        return {"piv": piv, "highs": [], "lows": [],
                "fractales_highs": [], "fractales_lows": [],
                "tendencia": "sin_datos",
                "motivo": f"hacen falta al menos {2 * piv + 3} velas"}
    tope = len(velas) - 1 if as_of_idx is None else as_of_idx
    highs, lows = smc.swing_points(velas, piv)
    paso = int(velas[1]["t"]) - int(velas[0]["t"])

    def enriquecer(p):
        return {
            **p,
            "pivot_t": int(velas[p["idx"]]["t"]),
            "confirmed_at": int(velas[p["confirm_idx"]]["t"]) + paso,
        }

    fractales_h = [enriquecer(p) for p in highs if p["confirm_idx"] <= tope]
    fractales_l = [enriquecer(p) for p in lows if p["confirm_idx"] <= tope]
    zigzag = pivotes_alternados(fractales_h, fractales_l)
    hs = [{k: v for k, v in p.items() if k != "tipo"}
          for p in zigzag if p["tipo"] == "high"]
    ls = [{k: v for k, v in p.items() if k != "tipo"}
          for p in zigzag if p["tipo"] == "low"]

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
    return {"piv": piv, "highs": hs[-6:], "lows": ls[-6:],
            "fractales_highs": fractales_h[-6:],
            "fractales_lows": fractales_l[-6:],
            "tendencia": tendencia,
            "n_highs": len(hs), "n_lows": len(ls),
            "n_fractales_highs": len(fractales_h),
            "n_fractales_lows": len(fractales_l),
            "retraso_velas": piv}


def pivotes_alternados(highs: list[dict], lows: list[dict]) -> list[dict]:
    """Zigzag causal de pivotes, resolviendo repeticiones del mismo tipo.

    Si aparecen dos highs sin un low intermedio, se conserva el más alto; para dos
    lows, el más bajo. El reemplazo ocurre solo cuando el segundo pivote ya está
    confirmado. Una vela que es high y low a la vez se excluye porque el OHLC no
    permite saber cuál extremo ocurrió primero.
    """
    por_idx = {}
    for tipo, puntos in (("high", highs), ("low", lows)):
        for p in puntos:
            por_idx.setdefault(p["idx"], []).append({"tipo": tipo, **p})

    secuencia = []
    for idx in sorted(por_idx):
        candidatos = por_idx[idx]
        if len({p["tipo"] for p in candidatos}) != 1:
            continue
        actual = candidatos[0]
        if not secuencia or secuencia[-1]["tipo"] != actual["tipo"]:
            secuencia.append(actual)
            continue
        anterior = secuencia[-1]
        mas_extremo = (actual["price"] > anterior["price"]
                       if actual["tipo"] == "high"
                       else actual["price"] < anterior["price"])
        if mas_extremo:
            secuencia[-1] = actual
    return secuencia


def piernas_confirmadas(velas: list[dict], tf: str, piv: int = 5) -> list[dict]:
    """Piernas entre pivotes opuestos consecutivos, ambos ya confirmados.

    No numera fases I-V ni elige retrospectivamente el swing más bonito. Cada par de
    pivotes opuestos contiguos es una candidata auditable y conserva cuándo quedó
    disponible el segundo extremo.
    """
    if len(velas) < 2 * piv + 3:
        return []
    highs, lows = smc.swing_points(velas, piv)
    puntos = pivotes_alternados(highs, lows)
    piernas = []
    paso = TF_MS[tf]
    for a, b in zip(puntos, puntos[1:]):
        direccion = "alcista" if a["tipo"] == "low" else "bajista"
        inicio, fin = float(a["price"]), float(b["price"])
        recorrido = fin - inicio
        if recorrido == 0:
            continue
        confirmado_idx = max(a["confirm_idx"], b["confirm_idx"])
        piernas.append({
            "direccion": direccion,
            "inicio": inicio,
            "fin": fin,
            "recorrido_abs": abs(recorrido),
            "inicio_idx": a["idx"],
            "fin_idx": b["idx"],
            "inicio_t": int(velas[a["idx"]]["t"]),
            "fin_t": int(velas[b["idx"]]["t"]),
            "confirm_idx": confirmado_idx,
            "confirmed_at": int(velas[confirmado_idx]["t"]) + paso,
            "selection_reason": "zigzag causal; pivotes repetidos colapsados al extremo",
            "piv": piv,
            "tf": tf,
        })
    return piernas


def mapa_precios(pierna: dict, precio: float) -> dict:
    """Retrocesos y extensiones aritméticas de una pierna ya congelada.

    Son escenarios calculados, no targets validados. La misma fórmula funciona en
    ambas direcciones porque el recorrido conserva su signo.
    """
    inicio = float(pierna["inicio"])
    fin = float(pierna["fin"])
    recorrido = fin - inicio
    retros = [{
        "ratio": r,
        "precio": fin - r * recorrido,
        "dist_pct": round(((fin - r * recorrido) / precio - 1) * 100, 2)
                    if precio else None,
    } for r in RETROCESOS]
    exts = [{
        "ratio": r,
        "precio": inicio + r * recorrido,
        "dist_pct": round(((inicio + r * recorrido) / precio - 1) * 100, 2)
                    if precio else None,
    } for r in EXTENSIONES]
    profundidad = (fin - precio) / recorrido if recorrido else None
    if profundidad is None:
        estado = "sin_datos"
    elif profundidad > 1:
        estado = "mas_alla_origen"
    elif profundidad < 0:
        estado = "extension"
    else:
        estado = "correccion"
    return {
        "pierna": pierna,
        "precio_actual": precio,
        "profundidad_correccion": round(profundidad, 4)
                                  if profundidad is not None else None,
        "estado": estado,
        "invalidacion_estructural_evaluada": False,
        "retrocesos": retros,
        "extensiones": exts,
        "invalidation_reference": inicio,
        "nota": "Mapa aritmético research; no es señal ni objetivo validado.",
    }


def alineacion_temporal(panorama: list[str], principal: str, sincronismo: str,
                        tendencias: dict[str, str]) -> dict:
    """Describe precedencia entre TF sin convertirla en un gate de entrada."""
    superiores = [tendencias.get(tf, "indefinida") for tf in panorama]
    direccion = (superiores[0]
                 if superiores and superiores[0] in ("alcista", "bajista")
                 and all(t == superiores[0] for t in superiores)
                 else None)
    principal_tendencia = tendencias.get(principal, "indefinida")
    sync_tendencia = tendencias.get(sincronismo, "indefinida")
    if direccion is None:
        estado = "contexto_superior_mixto_o_indefinido"
    elif principal_tendencia != direccion:
        estado = "principal_no_alineado"
    elif sync_tendencia == direccion:
        estado = "alineado"
    else:
        estado = "principal_alineado_sin_sincronismo"
    return {
        "estado": estado,
        "direccion_contexto": direccion,
        "tendencias": tendencias,
        "principal_alineado": bool(direccion and principal_tendencia == direccion),
        "sincronismo_alineado": bool(direccion and sync_tendencia == direccion),
        "nota": ("El timeframe superior define contexto; el inferior solo describe "
                 "sincronismo. No es un gate ni una señal validada."),
    }


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
