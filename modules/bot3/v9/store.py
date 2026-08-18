"""Bot3.v9 — almacén canónico append-only con hash encadenado.

Cláusulas: CF-17 (bytes y cadena), CF-22 (watermark causal de ingestión),
CF-28 (nacimiento M15 desde snapshot versionado), CF-31/CF-36 (marcador de
hueco con prueba probatoria), CF-32 (head causal por prefijo).

Invariante central: dos implementaciones que reciban las mismas fuentes —en
cualquier orden de llegada— producen el MISMO almacén, byte a byte. El
almacén es la única entrada del motor; su cadena de hashes lo prueba.
"""
from __future__ import annotations

import json
import os

from .contract import (
    TF_MS, WATERMARK_LOCAL_N, WATERMARK_EXCHANGE_N, WATERMARK_EXCHANGE_Q,
    canon, repr_f, sha256_hex,
)

SEMILLA = "0" * 64
FUENTE_PRIORIDAD = {"versionado": 0, "push": 1}   # menor gana (CF-22)


def ser_vela(c: dict) -> str:
    """Serialización canónica EXACTA de una vela (CF-17): `t` entero ms y
    OHLCV como shortest-repr float64 (cubre los CRUDOS que consume el motor,
    no valores cuantizados)."""
    return canon({
        "c": repr_f(c["c"]), "h": repr_f(c["h"]), "l": repr_f(c["l"]),
        "o": repr_f(c["o"]), "t": int(c["t"]), "v": repr_f(c["v"]),
    })


def ser_gap(desde: int, hasta: int, motivo: str, prueba) -> str:
    """Marcador canónico de hueco (CF-31/CF-36).

    `motivo="local"` → prueba = lista de los 3 primeros `close_time`
    cronológicos propios. `motivo="exchange"` → prueba = objeto
    {MERCADO: [t1,t2,t3]} con los Q mercados calificantes alfabéticos."""
    return canon({"desde": int(desde), "gap": True, "hasta": int(hasta),
                  "motivo": motivo, "prueba": prueba})


def detected_at(prueba) -> int:
    """`detected_at` = máximo de la estructura probatoria (CF-36)."""
    if isinstance(prueba, dict):
        return max(max(ts) for ts in prueba.values())
    return max(prueba)


def encadenar(prev_hex: str, payload: str) -> str:
    """`hash_acum(i) = SHA-256_hex(hash_acum(i-1) ‖ payload)`, con el hash
    previo concatenado como sus 64 caracteres ASCII hex (CF-17)."""
    return sha256_hex(prev_hex + payload)


class Almacen:
    """Almacén append-only de un (mercado, TF) con watermark de ingestión.

    Registros: velas y marcadores de hueco, cada uno con su `hash_acum`.
    Nada se reescribe jamás; los huecos son permanentes (CF-22).
    """

    def __init__(self, mercado: str, tf: str, ruta: str | None = None):
        self.mercado = mercado
        self.tf = tf
        self.dur = TF_MS[tf]
        self.ruta = ruta
        self.registros: list[dict] = []      # {"tipo","payload","hash_acum",...}
        self.velas: list[dict] = []          # solo velas, en orden
        self.ultimo_t: int | None = None     # None = almacén sin nacer
        self._buffer: dict[int, tuple[int, dict]] = {}   # t -> (prio, vela)
        self.incidencias: list[dict] = []
        # Índices (solo rendimiento; no alteran semántica): mapa t→vela,
        # rangos de hueco y caché de épocas invalidada en cada append.
        self._por_t: dict[int, dict] = {}
        self._huecos: list[tuple[int, int]] = []
        self._ts: list[int] = []
        self._epocas_cache: list[list[dict]] | None = None
        # Índices O(log n) para las consultas causales (mismos resultados que
        # el recorrido lineal, ver `test_b5_heads_indexados_equivalen`):
        #  - `_prefix_max[i]` = instante mínimo en que el PREFIJO 0..i es
        #    íntegramente consumible (máximo corrido de las disponibilidades:
        #    cierre de la vela, o `detected_at` del marcador). Es no
        #    decreciente, así que `head_asof` es un bisect.
        #  - `_vela_hashes[k]` = `hash_acum` de la k-ésima VELA, para que
        #    `commit_asof` sea un bisect sobre `_ts`.
        self._prefix_max: list[int] = []
        self._vela_hashes: list[str] = []

    # --- cadena ----------------------------------------------------------
    @property
    def head(self) -> str:
        return self.registros[-1]["hash_acum"] if self.registros else SEMILLA

    def _indexar(self, reg: dict) -> None:
        disp = (reg["t"] + self.dur) if reg["tipo"] == "vela" \
            else reg["detected_at"]
        previo = self._prefix_max[-1] if self._prefix_max else disp
        self._prefix_max.append(max(previo, disp))

    def _append(self, tipo: str, payload: str, **extra) -> dict:
        reg = {"tipo": tipo, "payload": payload,
               "hash_acum": encadenar(self.head, payload), **extra}
        self.registros.append(reg)
        self._indexar(reg)
        if self.ruta:
            os.makedirs(os.path.dirname(self.ruta), exist_ok=True)
            with open(self.ruta, "a", encoding="utf-8") as fh:
                fh.write(canon({k: v for k, v in reg.items()}) + "\n")
        return reg

    def _append_vela(self, vela: dict) -> None:
        t = int(vela["t"])
        self._append("vela", ser_vela(vela), t=t)
        self.velas.append(vela)
        self._vela_hashes.append(self.registros[-1]["hash_acum"])
        self._por_t[t] = vela
        self._ts.append(t)
        self.ultimo_t = t
        self._epocas_cache = None

    def _append_gap(self, desde: int, hasta: int, motivo: str, prueba) -> dict:
        reg = self._append("gap", ser_gap(desde, hasta, motivo, prueba),
                           desde=int(desde), hasta=int(hasta), motivo=motivo,
                           detected_at=detected_at(prueba))
        self._huecos.append((int(desde), int(hasta)))
        self.ultimo_t = int(hasta)
        self._epocas_cache = None
        return reg

    # --- rehidratación (B-6) ---------------------------------------------
    @classmethod
    def cargar(cls, mercado: str, tf: str, ruta: str) -> "Almacen":
        """Reconstruye el almacén desde su archivo append-only.

        Reconstruye TODOS los índices (`_prefix_max`, `_vela_hashes`,
        `_por_t`, `_ts`, `_huecos`) y VERIFICA la cadena: el `hash_acum` de
        cada registro debe reproducirse desde el anterior y su payload. Un
        archivo alterado no se carga en silencio."""
        alm = cls(mercado, tf, ruta=ruta)
        if not os.path.exists(ruta):
            return alm
        prev = SEMILLA
        with open(ruta, encoding="utf-8") as fh:
            for n, linea in enumerate(fh, 1):
                linea = linea.strip()
                if not linea:
                    continue
                reg = json.loads(linea)
                esperado = encadenar(prev, reg["payload"])
                if reg["hash_acum"] != esperado:
                    raise ValueError(
                        f"cadena rota en {ruta}:{n} — el almacén fue alterado")
                prev = reg["hash_acum"]
                alm.registros.append(reg)
                alm._indexar(reg)
                if reg["tipo"] == "vela":
                    datos = json.loads(reg["payload"])
                    vela = {"t": int(datos["t"]),
                            **{k: float(datos[k]) for k in "ohlcv"}}
                    alm.velas.append(vela)
                    alm._vela_hashes.append(reg["hash_acum"])
                    alm._por_t[vela["t"]] = vela
                    alm._ts.append(vela["t"])
                    alm.ultimo_t = vela["t"]
                else:
                    alm._huecos.append((reg["desde"], reg["hasta"]))
                    alm.ultimo_t = reg["hasta"]
        alm._epocas_cache = None
        return alm

    # --- nacimiento (CF-28) ----------------------------------------------
    def nacer_en(self, ancla_t: int) -> None:
        """Fija el ancla del almacén. Para H4 el ancla es GENESIS_H4; para
        M15, el menor `t` del snapshot versionado del commit de despliegue.
        `ultimo_t` queda una vela ANTES para que el ancla sea lo esperado."""
        if self.registros:
            raise RuntimeError("el almacén ya nació; no se puede re-anclar")
        self.ultimo_t = int(ancla_t) - self.dur

    # --- ingestión (CF-22) -----------------------------------------------
    def ofrecer(self, velas, fuente: str = "push") -> None:
        """Recibe velas de una fuente. Prioridad versionado > push durante
        TODA la permanencia en buffer; nada se appendea aquí."""
        prio = FUENTE_PRIORIDAD.get(fuente, 9)
        for v in velas:
            t = int(v["t"])
            if self.ultimo_t is not None and t <= self.ultimo_t:
                # Ya sellado: incidencia (revisada si difiere, no incorporada si no).
                self._incidencia(t, v)
                continue
            actual = self._buffer.get(t)
            if actual is None or prio < actual[0]:
                self._buffer[t] = (prio, v)

    def _incidencia(self, t: int, vela: dict) -> None:
        existente = next((v for v in self.velas if int(v["t"]) == t), None)
        difiere = existente is not None and ser_vela(existente) != ser_vela(vela)
        tipo = "vela_revisada" if difiere else "vela_no_incorporada"
        self.incidencias.append({
            "tipo": tipo, "mercado": self.mercado, "tf": self.tf, "t": t,
            "contenido_sha": sha256_hex(ser_vela(vela)),
        })

    def drenar(self) -> None:
        """Appendea el PREFIJO CONTINUO disponible desde `ultimo_t + dur`.
        Ninguna vela se appendea con su predecesora faltante (CF-22)."""
        if self.ultimo_t is None:
            return
        while True:
            siguiente = self.ultimo_t + self.dur
            entrada = self._buffer.pop(siguiente, None)
            if entrada is None:
                return
            self._append_vela(entrada[1])

    def hueco_pendiente(self) -> tuple[int, int] | None:
        """Rango del hueco que bloquea el avance, si lo hay (sin declarar)."""
        if self.ultimo_t is None or not self._buffer:
            return None
        siguiente = self.ultimo_t + self.dur
        if siguiente in self._buffer:
            return None
        t_min = min(self._buffer)
        return (siguiente, t_min - self.dur)

    def prueba_local(self) -> list[int] | None:
        """Los N primeros `close_time` cronológicos propios que satisfacen el
        watermark local (CF-36). None si aún no hay evidencia."""
        h = self.hueco_pendiente()
        if h is None:
            return None
        ts = sorted(self._buffer)
        if len(ts) < WATERMARK_LOCAL_N:
            return None
        return [t + self.dur for t in ts[:WATERMARK_LOCAL_N]]

    def declarar_hueco_local(self) -> dict | None:
        """Declara el hueco con prueba local si el watermark se cumplió."""
        h = self.hueco_pendiente()
        prueba = self.prueba_local()
        if h is None or prueba is None:
            return None
        reg = self._append_gap(h[0], h[1], "local", prueba)
        self.drenar()
        return reg

    def declarar_hueco_exchange(self, desde: int, hasta: int,
                                prueba: dict) -> dict:
        """Declara hueco por silencio con prueba de exchange (CF-29/CF-36)."""
        reg = self._append_gap(desde, hasta, "exchange", prueba)
        self.drenar()
        return reg

    # --- consulta causal (CF-32) -----------------------------------------
    def head_asof(self, t: int) -> str:
        """`input_head_asof_T`: head del último registro CONSUMIBLE en `t`
        (velas con `t_vela + dur ≤ t`; marcadores con `detected_at ≤ t`).
        Nunca el head físico del archivo (CF-32)."""
        import bisect
        k = bisect.bisect_right(self._prefix_max, t)
        return self.registros[k - 1]["hash_acum"] if k else SEMILLA

    def commit_asof(self, t: int) -> str:
        """`input_commit_asof_T` (CF-41 v13): `hash_acum` del ÚLTIMO registro
        de tipo VELA con `t_vela + dur ≤ t`.

        Identifica EXACTAMENTE el conjunto de velas consumidas —incluidas las
        posteriores a un hueco, porque esa cadena ya incorpora los marcadores
        intermedios— sin afirmar que el hueco fuera conocido antes de tiempo:
        es provenance de contenido, no conocimiento del modelo."""
        import bisect
        k = bisect.bisect_right(self._ts, t - self.dur)
        return self._vela_hashes[k - 1] if k else SEMILLA

    def head_finality(self, finalized_at: int) -> str:
        """`provenance_head_at_finality`: head del prefijo que INCLUYE el
        marcador/prueba que liberó el lote (CF-34)."""
        return self.head_asof(finalized_at)

    def velas_hasta(self, t: int) -> list[dict]:
        """Velas CERRADAS consumibles en `ahora = t` (CF-16)."""
        import bisect
        k = bisect.bisect_right(self._ts, t - self.dur)
        return self.velas[:k]

    def cubre(self, t: int) -> str:
        """Estado del instante `t` en el almacén: `vela`, `hueco` o `pendiente`."""
        if t in self._por_t:
            return "vela"
        for desde, hasta in self._huecos:
            if desde <= t <= hasta:
                return "hueco"
        return "pendiente"

    def epocas(self) -> list[list[dict]]:
        """Segmentos maximales continuos de velas (CF-13). Ningún objeto del
        modelo cruza un hueco."""
        if self._epocas_cache is not None:
            return self._epocas_cache
        out: list[list[dict]] = []
        actual: list[dict] = []
        prev: int | None = None
        for v in self.velas:
            t = int(v["t"])
            if prev is not None and t != prev + self.dur:
                out.append(actual)
                actual = []
            actual.append(v)
            prev = t
        if actual:
            out.append(actual)
        self._epocas_cache = out
        return out

    def epoca_de(self, t: int) -> list[dict] | None:
        for ep in self.epocas():
            if int(ep[0]["t"]) <= t <= int(ep[-1]["t"]):
                return ep
        return None

    def swings_full(self, L: int):
        """Pivotes de la serie COMPLETA con lookback `L`, cacheados. Los de
        cualquier prefijo se obtienen filtrando por `confirm_idx`
        (equivalencia exacta, ver `primitives.swings_prefijo`)."""
        cache = getattr(self, "_swings", None)
        if cache is None:
            cache = self._swings = {}
        hit = cache.get(L)
        if hit is not None and hit[0] == len(self.velas):
            return hit[1]
        from .primitives import swing_points
        res = swing_points(self.velas, L)
        cache[L] = (len(self.velas), res)
        return res

    def epoca_indice(self, t: int):
        """(inicio, fin) de índices de la época que contiene `t`, o None."""
        import bisect
        base = 0
        for ep in self.epocas():
            if int(ep[0]["t"]) <= t <= int(ep[-1]["t"]):
                k = bisect.bisect_right([int(v["t"]) for v in ep], t)
                return base, base + k
            base += len(ep)
        return None


def prueba_exchange(almacenes: dict, mercado_silencioso: str,
                    T: int) -> dict | None:
    """Prueba de watermark global (CF-29/CF-36): objeto con los Q mercados de
    referencia calificantes en orden ALFABÉTICO (si califican más, los Q
    primeros), cada uno con sus N `close_time` exactos requeridos.

    Califica un mercado de referencia que tenga velas appendeadas con
    `close_time ≥ T + n·dur` para n = 1..N."""
    dur = TF_MS["15m"]
    requeridos = [T + n * dur for n in range(1, WATERMARK_EXCHANGE_N + 1)]
    califican: dict[str, list[int]] = {}
    for mercado in sorted(almacenes):
        if mercado == mercado_silencioso:
            continue
        alm = almacenes[mercado]
        cierres = {int(v["t"]) + dur for v in alm.velas}
        if all(r in cierres for r in requeridos):
            califican[mercado] = list(requeridos)
    if len(califican) < WATERMARK_EXCHANGE_Q:
        return None
    elegidos = sorted(califican)[:WATERMARK_EXCHANGE_Q]
    return {m: califican[m] for m in elegidos}
