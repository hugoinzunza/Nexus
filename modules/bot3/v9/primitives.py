"""Bot3.v9 — primitivas normativas (diseño rev.3 §6-bis).

Definiciones EXACTAS y deterministas: dos implementaciones independientes de
este texto deben producir el mismo libro. Todo se computa sobre velas
cerradas de una época continua; nada mira el futuro (los pivotes se conocen
en `confirm_idx`, las rupturas exigen CUERPO).
"""
from __future__ import annotations

from .contract import (
    INT_PIV, OB_LOOKBACK, Q, STRUCT_PIV, SWEEP_LOOKBACK_SWINGS, TF_MS,
)


def swing_points(velas: list[dict], L: int):
    """Pivote con lookback `L`: `i` es swing high sii `h[i] > h[j]` para todo
    `j ∈ [i−L, i+L], j ≠ i` (desigualdad ESTRICTA: cualquier empate anula el
    pivote). `confirm_idx = i + L`."""
    highs, lows = [], []
    n = len(velas)
    for i in range(L, n - L):
        hi, lo = velas[i]["h"], velas[i]["l"]
        es_high = all(hi > velas[j]["h"] for j in range(i - L, i)) and \
            all(hi > velas[j]["h"] for j in range(i + 1, i + L + 1))
        es_low = all(lo < velas[j]["l"] for j in range(i - L, i)) and \
            all(lo < velas[j]["l"] for j in range(i + 1, i + L + 1))
        if es_high:
            highs.append({"idx": i, "price": hi, "confirm_idx": i + L})
        if es_low:
            lows.append({"idx": i, "price": lo, "confirm_idx": i + L})
    return highs, lows


def swings_prefijo(swings_full, n: int):
    """Pivotes de `velas[:n]` a partir de los del total.

    EQUIVALENCIA EXACTA: un pivote en `i` depende solo de `[i−L, i+L]`, y
    pertenece al prefijo de largo `n` sii `confirm_idx = i+L < n`. Filtrar es
    idéntico a recomputar, y evita O(n·L) por llamada."""
    sh, sl = swings_full
    return ([p for p in sh if p["confirm_idx"] < n],
            [p for p in sl if p["confirm_idx"] < n])


def bos_events(velas: list[dict], L: int, swings=None) -> list[dict]:
    """Rupturas de estructura CON CUERPO, algoritmo exacto del contrato:
    `cur` = el pivote CONFIRMADO de índice más alto con `idx > floor`; en la
    primera vela `j` con `c[j] > precio(cur)` (lado alto) se emite el evento,
    `floor = j`, `cur = None`. Disponible al cierre de `j`."""
    n = len(velas)
    closes = [v["c"] for v in velas]
    sh, sl = swings if swings is not None else swing_points(velas, L)
    hi_evt = sorted(sh, key=lambda p: p["confirm_idx"])
    lo_evt = sorted(sl, key=lambda p: p["confirm_idx"])
    hi_i = lo_i = 0
    cur_hi = cur_lo = None
    floor_hi = floor_lo = -1
    out = []
    for j in range(n):
        while hi_i < len(hi_evt) and hi_evt[hi_i]["confirm_idx"] <= j:
            p = hi_evt[hi_i]; hi_i += 1
            if p["idx"] > floor_hi and (cur_hi is None or p["idx"] > cur_hi["idx"]):
                cur_hi = p
        while lo_i < len(lo_evt) and lo_evt[lo_i]["confirm_idx"] <= j:
            p = lo_evt[lo_i]; lo_i += 1
            if p["idx"] > floor_lo and (cur_lo is None or p["idx"] > cur_lo["idx"]):
                cur_lo = p
        if cur_hi is not None and closes[j] > cur_hi["price"]:
            out.append({"j": j, "dir": "up", "swing": cur_hi})
            floor_hi = j
            cur_hi = None
        if cur_lo is not None and closes[j] < cur_lo["price"]:
            out.append({"j": j, "dir": "down", "swing": cur_lo})
            floor_lo = j
            cur_lo = None
    return out


def barre(vela: dict, precio: float, es_low: bool) -> bool:
    """Sweep: la vela `k` barre el swing low confirmado `p` sii
    `l[k] < precio(p)` y `c[k] ≥ precio(p)` (espejo para highs)."""
    if es_low:
        return vela["l"] < precio and vela["c"] >= precio
    return vela["h"] > precio and vela["c"] <= precio


def find_fvgs(velas: list[dict], desde: int, hasta: int, alcista: bool):
    """FVG alcista en `i`: `h[i−2] < l[i]` → zona `[h[i−2], l[i]]`.
    Bajista: `l[i−2] > h[i]` → `[h[i], l[i−2]]`. Disponible al cierre de `i`."""
    out = []
    for i in range(max(desde, 2), min(hasta, len(velas) - 1) + 1):
        a, c = velas[i - 2], velas[i]
        if alcista and a["h"] < c["l"]:
            out.append({"lo": a["h"], "hi": c["l"], "idx": i})
        if (not alcista) and a["l"] > c["h"]:
            out.append({"lo": c["h"], "hi": a["l"], "idx": i})
    return out


def find_ob(velas: list[dict], i_fvg: int, alcista: bool):
    """OB: última vela con cuerpo OPUESTO (largo: `c < o`) en
    `[i−6, i−2]` respecto del FVG `i`; zona = `[l, h]` de esa vela."""
    ini = max(0, i_fvg - OB_LOOKBACK)
    for i in range(min(i_fvg - 2, len(velas) - 1), ini - 1, -1):
        v = velas[i]
        opuesta = (v["c"] < v["o"]) if alcista else (v["c"] > v["o"])
        if opuesta:
            return {"lo": v["l"], "hi": v["h"], "idx": i}
    return None


def zonas_de_epoca(velas: list[dict], dur: int) -> list[dict]:
    """OB y FVG de la época, con `available_at` = cierre de la vela que
    completa el FVG (CF-6 tabla de disponibilidad)."""
    n = len(velas)
    out = []
    for alcista in (True, False):
        d = "long" if alcista else "short"
        for f in find_fvgs(velas, 2, n - 1, alcista):
            i = f["idx"]
            avail = int(velas[i]["t"]) + dur
            out.append({"kind": "fvg", "dir": d, "lo": Q(f["lo"]),
                        "hi": Q(f["hi"]), "idx": i, "available_at": avail})
            ob = find_ob(velas, i, alcista)
            if ob:
                out.append({"kind": "ob", "dir": d, "lo": Q(ob["lo"]),
                            "hi": Q(ob["hi"]), "idx": ob["idx"],
                            "available_at": avail})
    # Dedupe por caja conservando la de available_at más antiguo.
    vistas, ded = {}, []
    for z in sorted(out, key=lambda z: (z["available_at"], z["kind"], z["lo"], z["hi"])):
        k = (z["kind"], z["dir"], z["lo"], z["hi"])
        if k in vistas:
            continue
        vistas[k] = True
        ded.append(z)
    return ded


def fractal_50(velas: list[dict], dur: int, swings=None):
    """Fractal ≥50%: pierna entre los últimos swings STRUCT confirmados (el
    de índice menor es el origen); anclaje en los EXTREMOS con mecha;
    `fib50 = (a+b)/2`; alcanzado sii alguna vela POSTERIOR al extremo final
    cumple `l ≤ fib50` (pierna alcista) o `h ≥ fib50` (bajista).
    Devuelve dict con `available_at` = cierre de esa vela, o None."""
    n = len(velas)
    sh, sl = swings if swings is not None else swing_points(velas, STRUCT_PIV)
    hs = [p for p in sh if p["confirm_idx"] < n]
    ls = [p for p in sl if p["confirm_idx"] < n]
    if not hs or not ls:
        return None
    h, l = hs[-1], ls[-1]
    up = l["idx"] < h["idx"]
    a, b = (l, h) if up else (h, l)
    if a["idx"] >= b["idx"]:
        return None
    fib = Q((a["price"] + b["price"]) / 2)
    for k in range(b["idx"] + 1, n):
        alcanzado = (velas[k]["l"] <= fib) if up else (velas[k]["h"] >= fib)
        if alcanzado:
            return {"dir": "alcista" if up else "bajista", "fib50": fib,
                    "available_at": int(velas[k]["t"]) + dur}
    return None


def rango_rector(velas: list[dict], dur: int, swings_struct=None,
                 swings_int=None):
    """Rango rector H4 (fail closed).

    - dirección = último BOS con cuerpo vigente;
    - tramo origen = desde la ruptura OPUESTA previa (si no existe →
      `rango_sin_origen`, CF-1);
    - `strong` = extremo del tramo, VÁLIDO solo con sweep verificable;
    - `weak` provisional = extremo post-BOS; CERRADO cuando después confirma
      un swing INT y ocurre un iBOS opuesto (finalización);
    - si un swing STRUCT confirmado SIN BARRER queda más allá del weak, el
      weak se extiende al MÁS CERCANO de ellos (liquidez pendiente).
    Devuelve dict o {"abstencion": motivo}.
    """
    n = len(velas)
    if swings_struct is None:
        swings_struct = swing_points(velas, STRUCT_PIV)
    if swings_int is None:
        swings_int = swing_points(velas, INT_PIV)
    bos = bos_events(velas, STRUCT_PIV, swings=swings_struct)
    if not bos:
        return {"abstencion": "direccion_desconocida"}
    e = bos[-1]
    j = e["j"]
    up = e["dir"] == "up"
    prev_opp = [b for b in bos if b["dir"] != e["dir"] and b["j"] < j]
    if not prev_opp:
        return {"abstencion": "rango_sin_origen"}
    inicio = prev_opp[-1]["j"]
    tramo = range(inicio, j + 1)

    if up:
        k0 = min(tramo, key=lambda k: velas[k]["l"])
        strong = velas[k0]["l"]
    else:
        k0 = max(tramo, key=lambda k: velas[k]["h"])
        strong = velas[k0]["h"]

    # Sweep verificable en el origen (§6-bis): el origen "tomó liquidez" sii
    # ALGUNA vela del tramo origen barre ≥1 de los últimos 6 swings INT
    # confirmados previos al extremo (no solo la vela del extremo).
    sh_prev, sl_prev = swings_prefijo(swings_int, k0 + 1)
    previos = [p for p in (sl_prev if up else sh_prev)
               if p["confirm_idx"] <= k0][-SWEEP_LOOKBACK_SWINGS:]
    sweep = any(barre(velas[k], p["price"], es_low=up)
                for k in tramo for p in previos)
    if not sweep:
        return {"abstencion": "rango_sin_origen"}

    # Weak provisional = extremo post-BOS.
    if up:
        kw = max(range(j, n), key=lambda k: velas[k]["h"])
        weak = velas[kw]["h"]
    else:
        kw = min(range(j, n), key=lambda k: velas[k]["l"])
        weak = velas[kw]["l"]

    # Finalización: swing INT confirmado + iBOS opuesto tras el extremo.
    cola = velas[kw:]
    cerrado = False
    fin_t = None
    if len(cola) > 2 * INT_PIV + 2:
        for b in bos_events(cola, INT_PIV):
            if b["dir"] != e["dir"]:
                cerrado = True
                fin_t = int(cola[b["j"]]["t"]) + dur
                break
    if not cerrado:
        return {"abstencion": "sin_weak_cerrado"}

    # Extensión a liquidez pendiente MÁS CERCANA más allá del weak.
    sh_all, sl_all = swings_struct
    if up:
        cands = [p for p in sh_all if p["price"] > weak and p["confirm_idx"] < n
                 and not any(velas[k]["h"] > p["price"]
                             for k in range(p["idx"] + 1, n))]
        if cands:
            weak = min(cands, key=lambda p: p["price"])["price"]
    else:
        cands = [p for p in sl_all if p["price"] < weak and p["confirm_idx"] < n
                 and not any(velas[k]["l"] < p["price"]
                             for k in range(p["idx"] + 1, n))]
        if cands:
            weak = max(cands, key=lambda p: p["price"])["price"]

    strong, weak = Q(strong), Q(weak)
    if strong == weak:
        return {"abstencion": "sin_weak_cerrado"}
    lo, hi = (strong, weak) if up else (weak, strong)
    return {
        "dir": "long" if up else "short",
        "strong": strong, "weak": weak, "eq": Q((strong + weak) / 2),
        "lo": lo, "hi": hi,
        "bos_t": int(velas[j]["t"]) + dur,      # available_at de la dirección
        "bos_idx": j, "fin_t": fin_t,
    }


def direccion_vigente(velas: list[dict], dur: int, expira_velas: int,
                      swings=None):
    """Dirección rectora con expiración (fail closed): la última ruptura con
    cuerpo; expira si pasaron `expira_velas` sin BOS de continuación."""
    bos = bos_events(velas, STRUCT_PIV, swings=swings)
    if not bos:
        return None, "direccion_desconocida"
    e = bos[-1]
    if (len(velas) - 1) - e["j"] > expira_velas:
        return None, "direccion_expirada"
    return ("long" if e["dir"] == "up" else "short"), None


# --- Ciclo del candidato (v13: CF-39) --------------------------------------
def zona_derivada(velas: list[dict], j_ibos: int, largo: bool, dur: int,
                  swings_int=None):
    """Zona creada POR EL DESPLAZAMIENTO del iBOS (CF-39.3, normativo).

    - `j_origen` = idx del ÚLTIMO swing INT con `confirm_idx ≤ j_ibos` e
      `idx < j_ibos`, tomado LITERALMENTE del lado: LONG → swing LOW;
      SHORT → swing HIGH.
    - Desplazamiento = velas `[j_origen, j_ibos]`.
    - **OB del desplazamiento** = la ÚLTIMA vela del tramo con cuerpo
      OPUESTO al trade (largo: `c < o`); su caja es `[l, h]`.
    - **Fallback FVG**: si no hay vela de cuerpo opuesto, el FVG de la
      dirección con vela de formación en `(j_origen, j_ibos]` de `idx`
      MÍNIMO (el más cercano al origen); empate → menor `lo`.

    Devuelve dict con `lo`, `hi`, `kind`, `zone_formation_at` y
    `order_available_at` (= cierre de `j_ibos`, CF-39.4), o None.
    """
    sh, sl = swings_int if swings_int is not None else swing_points(velas, INT_PIV)
    lado = sl if largo else sh
    previos = [p for p in lado
               if p["confirm_idx"] <= j_ibos and p["idx"] < j_ibos]
    if not previos:
        return None
    j_origen = previos[-1]["idx"]
    order_avail = int(velas[j_ibos]["t"]) + dur

    for i in range(j_ibos, j_origen - 1, -1):        # OB: la ÚLTIMA opuesta
        v = velas[i]
        opuesta = (v["c"] < v["o"]) if largo else (v["c"] > v["o"])
        if opuesta:
            return {"kind": "ob", "lo": Q(v["l"]), "hi": Q(v["h"]),
                    "zone_formation_at": int(v["t"]) + dur,
                    "order_available_at": order_avail, "j_origen": j_origen}

    candidatas = [f for f in find_fvgs(velas, j_origen + 1, j_ibos, largo)
                  if j_origen < f["idx"] <= j_ibos]
    if not candidatas:
        return None
    f = min(candidatas, key=lambda x: (x["idx"], Q(x["lo"])))
    return {"kind": "fvg", "lo": Q(f["lo"]), "hi": Q(f["hi"]),
            "zone_formation_at": int(velas[f["idx"]]["t"]) + dur,
            "order_available_at": order_avail, "j_origen": j_origen}


def primera_toma(velas: list[dict], j_toque: int, hasta: int, largo: bool,
                 swings_int=None):
    """`j_toma` (CF-39.1): la PRIMERA vela `k > j_toque` que BARRE un swing
    INT del lado correspondiente **disponible antes de `k`**
    (`confirm_idx < k`, disponibilidad causal M-3). None si aún no ocurre."""
    sh, sl = swings_int if swings_int is not None else swing_points(velas, INT_PIV)
    lado = sl if largo else sh
    for k in range(j_toque + 1, min(hasta, len(velas))):
        for p in lado:
            if p["confirm_idx"] >= k or p["idx"] >= k:
                continue
            if barre(velas[k], p["price"], es_low=largo):
                return k
    return None
