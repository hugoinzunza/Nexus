"""Bot3.v9 — motor del submodelo single-entry H4→M15.

Cláusulas: CF-2 (salidas con gap), CF-3 (R planificado), CF-4 (costos),
CF-8 (funding causal), CF-13 (épocas), CF-14 (ciclo de 8 fases con cálculo
puro antes de aplicar), CF-15 (raw vs Q), CF-16 (`ahora`), CF-18
(trayectoria indeterminada), CF-19/CF-23 (lotes globales y finalidad),
CF-20 (fill+STOP), CF-24 (bootstrap), CF-34 (temporalidad triple y heads
duales), CF-35 (corte administrativo total), y del protocolo v13:
CF-38 (estado `candidato_vivo` y partición de eventos), CF-39 (cronología
POST-toque determinista: j_toma → primer iBOS con zona derivada → orden),
CF-40 (Fase 7 desdoblada con precedencia única) y CF-42 (`ganador` del
arbitraje).

El motor no ejecuta órdenes ni conoce credenciales: produce eventos.
"""
from __future__ import annotations

import bisect

from . import primitives as P
from .contract import (
    CORTE_MIN_SEMANAS_ISO, CORTE_N_CIERRES, DEADLINE_M15, DIR_EXPIRA_H4,
    GENESIS_H4,
    EPOCA_M15_MIN_VELAS, FEE_MAKER, FEE_TAKER, FUNDING_HORAS_UTC,
    FUNDING_RATE, INT_PIV, Q, RR_MIN, SLIPPAGE_STOP, SL_BUFFER, TF_MS,
    TTL_ZONA_H4, T_CORTE, VENTANA_IBOS_M15,
    candidate_id, order_id, trade_id,
)

DUR_M15 = TF_MS["15m"]
DUR_H4 = TF_MS["4h"]
FUNDING_PERIODO = 8 * 3_600_000


# --- Fill y salidas (§4.5 v2 y CF-2, con la política numérica CF-15) -------
def evaluar_fill(vela: dict, E: float, S: float, largo: bool):
    """Devuelve (resultado, precio) donde resultado ∈ {None, "gap_ambiguo",
    "fill", "fill_stop"}. `E` y `S` ya vienen cuantizados."""
    o, h, l = vela["o"], vela["h"], vela["l"]
    if largo:
        if o <= S:
            return "gap_ambiguo", None
        if o <= E:
            p_in = Q(o)                      # gap a favor → fill al OPEN
        elif l <= E:
            p_in = E
        else:
            return None, None
        # STOP en la MISMA vela del fill (CF-20); nunca TP aquí.
        if l <= S:
            return "fill_stop", p_in
        return "fill", p_in
    if o >= S:
        return "gap_ambiguo", None
    if o >= E:
        p_in = Q(o)
    elif h >= E:
        p_in = E
    else:
        return None, None
    if h >= S:
        return "fill_stop", p_in
    return "fill", p_in


def evaluar_salida(vela: dict, S: float, T: float, largo: bool):
    """CF-2: (motivo, P_out) o (None, None). Orden normativo: gap-SL →
    gap-TP → SL → TP; SL y TP en la misma vela = STOP."""
    o, h, l = vela["o"], vela["h"], vela["l"]
    if largo:
        if o <= S:
            base = Q(o)
            return "stop", Q(base * (1 - SLIPPAGE_STOP))
        if o >= T:
            return "tp", Q(o)
        if l <= S:
            base = Q(S)
            return "stop", Q(base * (1 - SLIPPAGE_STOP))
        if h >= T:
            return "tp", Q(T)
        return None, None
    if o >= S:
        base = Q(o)
        return "stop", Q(base * (1 + SLIPPAGE_STOP))
    if o <= T:
        return "tp", Q(o)
    if h >= S:
        base = Q(S)
        return "stop", Q(base * (1 + SLIPPAGE_STOP))
    if l <= T:
        return "tp", Q(T)
    return None, None


def devengos_funding(close_fill: int, close_salida: int) -> list[int]:
    """CF-8: todo `k` (00/08/16 UTC) con
    `close_time(fill) < k ≤ close_time(salida)`."""
    if close_salida <= close_fill:
        return []
    primero = (close_fill // FUNDING_PERIODO + 1) * FUNDING_PERIODO
    return list(range(primero, close_salida + 1, FUNDING_PERIODO))


def rr_a_priori(E: float, S: float, T: float) -> float:
    """CF-4: solo costos deterministas (entrada + salida TP maker)."""
    riesgo = abs(E - S)
    if riesgo <= 0:
        return 0.0
    return (abs(T - E) - FEE_MAKER * E - FEE_MAKER * T) / riesgo


def resultado_r(P_in: float, P_out: float, E: float, S: float, largo: bool,
                motivo: str, fundings: list[float]) -> tuple[float, float]:
    """CF-3 + CF-4: PnL neto y R con unidad de riesgo PLANIFICADA |E−S|.
    Sin redondeo intermedio; solo el reporte se redondea (4 decimales)."""
    dirn = 1.0 if largo else -1.0
    pnl_bruto = dirn * (P_out - P_in)
    fee_in = FEE_MAKER * P_in
    fee_out = (FEE_MAKER if motivo == "tp" else FEE_TAKER) * P_out
    pnl_neto = pnl_bruto - fee_in - fee_out - sum(fundings)
    r = pnl_neto / abs(E - S)
    return pnl_neto, r


# --- Estado por mercado ----------------------------------------------------
class EstadoMercado:
    """Máquina de estados CF-38 (v13):

    `flat → candidato_vivo → orden_viva → posicion → (salida_detectada) → flat`

    Los eventos están PARTICIONADOS por estado: un candidato jamás emite
    `orden_*` y una orden jamás emite `candidato_*`."""

    def __init__(self, mercado: str):
        self.mercado = mercado
        self.estado = "flat"
        self.degradado = False
        self.candidato = None    # CF-38: dict del candidato vivo
        self.orden = None        # dict con E,S,T,ids,deadline,largo,...
        self.posicion = None     # dict con P_in, E, S, T, ids, close_fill,...
        self.salida = None       # transitorio de la fase 1a
        self.zonas_tocadas: set[tuple] = set()   # frescura consumida (CF-24)


class Motor:
    """Orquesta los lotes globales por `close_time` M15 (CF-19/CF-23)."""

    def __init__(self, almacenes_m15: dict, almacenes_h4: dict,
                 mercados: tuple, ledger, bootstrap_hasta: int | None = None):
        self.m15 = almacenes_m15
        self.h4 = almacenes_h4
        self.mercados = tuple(sorted(mercados))
        self.ledger = ledger
        self.estados = {m: EstadoMercado(m) for m in self.mercados}
        self.bootstrap_hasta = bootstrap_hasta   # T_frontera (CF-21/CF-24)
        self.cierres: list[dict] = []            # cohorte evaluable
        self.lotes_finalizados: list[int] = []
        self.cortado = False

    # --- utilidades -------------------------------------------------------
    def _emitiendo(self, T: int) -> bool:
        """CF-21/CF-24: durante el bootstrap se ejecutan TODAS las
        transiciones (frescura incluida) pero no se emite al ledger."""
        return self.bootstrap_hasta is None or T > self.bootstrap_hasta

    def _emit(self, tipo: str, T: int, mercado: str | None = None,
              finalized_at: int | None = None, processed_at: int | None = None,
              **campos) -> None:
        if not self._emitiendo(T):
            return
        fin = T if finalized_at is None else finalized_at
        heads = {}
        if mercado:
            heads = {
                "input_head_asof_T": self.m15[mercado].head_asof(T),
                "provenance_head_at_finality": self.m15[mercado].head_finality(fin),
                "h4_head_asof_T": self.h4[mercado].head_asof(T),
            }
            ep = self.m15[mercado].epoca_de(T - DUR_M15)
            if ep:
                heads["epoca_m15"] = int(ep[0]["t"])
        self.ledger.append(tipo, mercado=mercado, effective_at=T,
                           finalized_at=fin,
                           processed_at=T if processed_at is None else processed_at,
                           **heads, **campos)

    def _epoca_habilitada(self, mercado: str, T: int):
        """(época, k) donde `época[:k]` son las velas de la ÉPOCA vigente ya
        cerradas en `T` (CF-13: ningún objeto del modelo cruza un hueco).

        Devuelve la lista y el índice —no una copia— para no pagar O(n) por
        lote: los consumidores toman solo la cola que necesitan."""
        alm = self.m15[mercado]
        ep = alm.epoca_de(T - DUR_M15)
        if ep is None:
            return None
        lo, hi = 0, len(ep)
        while lo < hi:                           # bisect sin copiar la lista
            mid = (lo + hi) // 2
            if int(ep[mid]["t"]) <= T - DUR_M15:
                lo = mid + 1
            else:
                hi = mid
        # La habilitación se mide sobre las velas CERRADAS en T, nunca sobre
        # el tamaño físico de la época (que incluye futuro del almacén).
        # Medirlo con `len(ep)` era look-ahead (auditoría 2026-08-17, B-1).
        if lo < EPOCA_M15_MIN_VELAS:
            return None
        return (ep, lo)

    # --- lote (CF-19/CF-23) ----------------------------------------------
    def lote_finalizable(self, T: int) -> bool:
        """Finalizable sii cada mercado tiene vela en T, un marcador de hueco
        que cubre T, o no tiene época habilitada."""
        for m in self.mercados:
            estado = self.m15[m].cubre(T - DUR_M15)
            if estado == "vela" or estado == "hueco":
                continue
            if self._epoca_habilitada(m, T) is None:
                continue
            return False
        return True

    def procesar_lote(self, T: int, finalized_at: int | None = None) -> None:
        """Fases 1–7 por mercado en orden canónico + Fase 8 global."""
        if self.cortado:
            return
        if T > T_CORTE:                      # pre-gate temporal (CF-19)
            self._cerrar_por_tiempo(T)
            return
        fin = T if finalized_at is None else finalized_at
        for mercado in self.mercados:
            self._procesar_mercado(mercado, T, fin)
        self._emit("lote_finalizado", T, finalized_at=fin)
        self.lotes_finalizados.append(T)
        self._fase8(T)

    def _procesar_mercado(self, mercado: str, T: int, fin: int) -> None:
        st = self.estados[mercado]
        alm = self.m15[mercado]
        idx_t = T - DUR_M15
        cubre = alm.cubre(idx_t)

        # Hueco que intersecta: CF-18 fail-closed.
        if cubre == "hueco":
            if st.estado == "candidato_vivo":
                self._emit("candidato_expirado", T, mercado, finalized_at=fin,
                           id=st.candidato["candidate_id"], motivo="hueco_m15")
                st.candidato = None
                st.estado = "flat"
            elif st.estado == "orden_viva":
                self._emit("orden_cancelada", T, mercado, finalized_at=fin,
                           id=st.orden["order_id"], motivo="hueco_m15")
                st.orden = None
                st.estado = "flat"
            elif st.estado in ("posicion", "salida_detectada"):
                pos = st.posicion
                self._emit("trayectoria_indeterminada", T, mercado,
                           finalized_at=fin, id=pos["trade_id"],
                           effective_hueco=pos["ultimo_cierre_sellado"])
                st.posicion = None
                st.salida = None
                st.estado = "flat"
            return
        if cubre != "vela":
            return

        ventana = self._epoca_habilitada(mercado, T)
        if ventana is None:
            return
        ep, k = ventana
        vela = ep[k - 1]
        if int(vela["t"]) != idx_t:
            return

        # FASE 1a — resolución intravela de posición → salida_detectada.
        if st.estado == "posicion":
            pos = st.posicion
            motivo, p_out = evaluar_salida(vela, pos["S"], pos["T"], pos["largo"])
            if motivo:
                st.salida = {"motivo": motivo, "P_out": p_out, "close": T}
                st.estado = "salida_detectada"
            else:
                pos["ultimo_cierre_sellado"] = T

        # FASE 1b — fill de la orden viva (firme).
        if st.estado == "orden_viva":
            o = st.orden
            if T > o["deadline_close"]:
                pass                                     # se cancela en Fase 5
            else:
                res, p_in = evaluar_fill(vela, o["E"], o["S"], o["largo"])
                if res == "gap_ambiguo":
                    self._emit("gap_ambiguo", T, mercado, finalized_at=fin,
                               id=o["order_id"])
                    st.orden = None
                    st.estado = "flat"
                elif res in ("fill", "fill_stop"):
                    tid = trade_id(o["order_id"], T, p_in)
                    st.posicion = {**o, "P_in": p_in, "trade_id": tid,
                                   "close_fill": T, "ultimo_cierre_sellado": T}
                    self._emit("fill", T, mercado, finalized_at=fin, id=tid,
                               precio=p_in)
                    if res == "fill_stop":
                        # CF-20: orden_viva → salida_detectada directo.
                        _, p_out = evaluar_salida(vela, o["S"], o["T"], o["largo"])
                        if p_out is None:
                            base = Q(o["S"])
                            p_out = Q(base * (1 - SLIPPAGE_STOP)) if o["largo"] \
                                else Q(base * (1 + SLIPPAGE_STOP))
                        st.salida = {"motivo": "stop", "P_out": p_out, "close": T}
                        st.estado = "salida_detectada"
                    else:
                        st.estado = "posicion"

        # FASE 2 — cálculo PURO del cierre (sin aplicar).
        calc = self._calcular(mercado, T)

        # FASE 3 + 4 — funding y consolidación del único evento `cerrado`.
        if st.estado == "salida_detectada":
            self._consolidar_cierre(mercado, T, fin)

        # FASE 5 — cancelaciones con el estado recién calculado.
        if st.estado == "orden_viva":
            o = st.orden
            motivo = None
            # CF-38/v13: el deadline se resuelve AL AGOTARSE (>=), no una
            # vela después; y precede a la cancelación por dirección para
            # que el terminal sea unívoco. La vela del deadline ya tuvo su
            # oportunidad de fill en la Fase 1b (que usa >).
            if T >= o["deadline_close"]:
                motivo = "deadline"
            elif calc["direccion"] != o["dir"]:
                motivo = "direccion"
            if motivo:
                tipo = "confirmada_sin_fill" if motivo == "deadline" else "orden_cancelada"
                self._emit(tipo, T, mercado, finalized_at=fin,
                           id=o["order_id"], motivo=motivo)
                st.orden = None
                st.estado = "flat"

        # FASE 6 — aplicar estado estructural (implícito: `calc` es la vista).
        # FASE 7a — candidato vivo (CF-40): invalidación → orden → deadline
        # → dirección/hueco, en ese orden normativo único.
        if st.estado == "candidato_vivo":
            self._fase7a(mercado, T, fin, ep, k, calc, st)
        # FASE 7b — nuevo candidato (nunca orden en la vela del toque).
        if st.estado == "flat" and not st.degradado:
            self._fase7b(mercado, T, fin, ep, k, calc, st)

    # --- Fase 2: cálculo puro --------------------------------------------
    def _calcular(self, mercado: str, T: int) -> dict:
        # La estructura H4 es función PURA de las velas H4 con cierre ≤ T:
        # solo cambia cuando cierra una vela H4. Cachear por esa frontera es
        # exacto (no altera resultados) y evita rehacer O(n) por cada lote.
        frontera = (T // DUR_H4) * DUR_H4
        cache = getattr(self, "_cache_h4", None)
        if cache is None:
            cache = self._cache_h4 = {}
        hit = cache.get(mercado)
        if hit and hit[0] == frontera:
            return hit[1]
        calc = self._calcular_h4(mercado, T)
        cache[mercado] = (frontera, calc)
        return calc

    def _calcular_h4(self, mercado: str, T: int) -> dict:
        alm = self.h4[mercado]
        h4 = alm.velas_hasta(T)
        insuf = {"direccion": None, "motivo": "historia_insuficiente",
                 "rango": None, "zonas": [], "fractal": None}
        if len(h4) < 3 * P.STRUCT_PIV:
            return insuf
        # CF-13: H4 exige ÉPOCA ÚNICA continua desde GENESIS_H4 hasta `T`.
        # La continuidad se evalúa SOLO sobre el prefijo causal: un hueco
        # POSTERIOR a T no puede volver insuficiente un instante anterior
        # (era look-ahead — auditoría 2026-08-17, B-1).
        epocas = alm.epocas()
        if not epocas or int(epocas[0][0]["t"]) != GENESIS_H4:
            return insuf
        if int(epocas[0][-1]["t"]) + DUR_H4 < T:     # T cae tras el 1er hueco
            return insuf
        n = len(h4)
        s_struct = P.swings_prefijo(alm.swings_full(P.STRUCT_PIV), n)
        s_int = P.swings_prefijo(alm.swings_full(INT_PIV), n)
        rango = P.rango_rector(h4, DUR_H4, swings_struct=s_struct,
                               swings_int=s_int)
        if "abstencion" in rango:
            return {"direccion": None, "motivo": rango["abstencion"],
                    "rango": None, "zonas": [], "fractal": None}
        direccion, motivo = P.direccion_vigente(h4, DUR_H4, DIR_EXPIRA_H4,
                                                swings=s_struct)
        fractal = P.fractal_50(h4, DUR_H4, swings=s_struct)
        zonas = [z for z in P.zonas_de_epoca(h4, DUR_H4)
                 if z["available_at"] <= T
                 and z["available_at"] + TTL_ZONA_H4 * DUR_H4 >= T]
        return {"direccion": direccion, "motivo": motivo, "rango": rango,
                "zonas": zonas, "fractal": fractal}

    # --- Fases 3-4: funding y cierre definitivo --------------------------
    def _consolidar_cierre(self, mercado: str, T: int, fin: int) -> None:
        st = self.estados[mercado]
        alm = self.m15[mercado]
        pos, sal = st.posicion, st.salida
        ks = devengos_funding(pos["close_fill"], sal["close"])
        # CF-8: `C_k` = cierre de la vela M15 cuyo `close_time == k`.
        fundings = []
        for k in ks:
            v = alm._por_t.get(k - DUR_M15)
            if v is not None:
                fundings.append(FUNDING_RATE * Q(v["c"]))
        pnl, r = resultado_r(pos["P_in"], sal["P_out"], pos["E"], pos["S"],
                             pos["largo"], sal["motivo"], fundings)
        self._emit("cerrado", T, mercado, finalized_at=fin, id=pos["trade_id"],
                   motivo=sal["motivo"], precio_salida=sal["P_out"],
                   pnl_neto=pnl, r=round(r, 4), fundings=len(fundings))
        if self._emitiendo(T):
            self.cierres.append({"t": T, "mercado": mercado, "r": r,
                                 "trade_id": pos["trade_id"]})
        st.posicion = None
        st.salida = None
        st.estado = "flat"

    # --- Fase 7: toque, confirmación M15, arbitraje y orden --------------
    def _fase7b(self, mercado: str, T: int, fin: int, ep: list[dict], k: int,
                calc: dict, st: EstadoMercado) -> None:
        """Detecta toque, arbitra y CREA EL CANDIDATO. Nunca crea orden en la
        misma vela del toque (CF-40)."""
        direccion, rango = calc["direccion"], calc["rango"]
        if direccion is None or rango is None:
            self._emit("abstencion", T, mercado, finalized_at=fin,
                       motivo=calc.get("motivo") or "direccion_desconocida")
            return
        fractal = calc["fractal"]
        if fractal is None or fractal["available_at"] > T:
            return
        vela = ep[k - 1]
        eq = rango["eq"]

        # Zonas H4 elegibles TOCADAS en esta vela M15.
        elegibles = []
        for z in calc["zonas"]:
            if z["dir"] != direccion:
                continue
            lado_ok = (z["lo"] + z["hi"]) / 2 < eq if direccion == "long" \
                else (z["lo"] + z["hi"]) / 2 > eq
            if not lado_ok:
                continue
            clave = (z["kind"], z["dir"], z["lo"], z["hi"], z["available_at"])
            if clave in st.zonas_tocadas:          # frescura consumida (CF-24)
                continue
            if vela["l"] <= z["hi"] and vela["h"] >= z["lo"]:
                elegibles.append((z, clave))
        if not elegibles:
            return

        # Arbitraje determinista (§5 del diseño).
        def orden_arb(item):
            z, _ = item
            proximal = z["hi"] if direccion == "long" else z["lo"]
            return (z["available_at"], 0 if z["kind"] == "ob" else 1,
                    abs(proximal - vela["c"]), z["lo"])
        elegibles.sort(key=orden_arb)
        ganadora, clave = elegibles[0]
        cid_ganador = candidate_id(mercado, direccion, ganadora["available_at"],
                                   ganadora["lo"], ganadora["hi"], T)
        for z, _k in elegibles[1:]:
            # CF-42: referencia obligatoria al ganador.
            self._emit("descartada_por_arbitraje", T, mercado, finalized_at=fin,
                       id=candidate_id(mercado, direccion, z["available_at"],
                                       z["lo"], z["hi"], T),
                       ganador=cid_ganador)
        # La frescura se consume con el TOQUE (también en bootstrap).
        for _z, clave_z in elegibles:
            st.zonas_tocadas.add(clave_z)

        cid = cid_ganador
        self._emit("candidato", T, mercado, finalized_at=fin, id=cid)
        # CF-38: nace el candidato vivo; la confirmación ocurre en velas
        # POSTERIORES (CF-39). La frescura ya se consumió con el toque.
        st.candidato = {
            "candidate_id": cid, "zona": ganadora, "dir": direccion,
            "mercado": mercado,
            "largo": direccion == "long", "j_toque": k - 1,
            "close_toque": T, "deadline_close": T + DEADLINE_M15 * DUR_M15,
            "weak": rango["weak"],
        }
        st.estado = "candidato_vivo"

    # --- Fase 7a: ciclo del candidato vivo (CF-39/CF-40) -----------------
    def _fase7a(self, mercado: str, T: int, fin: int, ep: list[dict], k: int,
                calc: dict, st: EstadoMercado) -> None:
        cand = st.candidato
        vela = ep[k - 1]
        z = cand["zona"]
        largo = cand["largo"]

        # (a) INVALIDACIÓN: cierre M15 a través de la invalidación de la zona.
        far = z["lo"] if largo else z["hi"]
        if (vela["c"] < far) if largo else (vela["c"] > far):
            self._emit("candidato_invalidado", T, mercado, finalized_at=fin,
                       id=cand["candidate_id"])
            st.candidato = None
            st.estado = "flat"
            return

        # (b) ORDEN: par ganador (CF-39.2) con zona derivada completada ≤ T.
        par = self._par_ganador(ep, k, cand)
        if par is not None:
            E, S, deriv = par
            Tp = cand["weak"]
            coherente = (S < E < Tp) if largo else (Tp < E < S)
            if coherente and rr_a_priori(E, S, Tp) >= RR_MIN:
                oid = order_id(cand["candidate_id"],
                               deriv["order_available_at"],
                               deriv["lo"], deriv["hi"])
                self._emit("orden_creada", T, mercado, finalized_at=fin,
                           id=oid, entrada=E, sl=S, tp=Tp,
                           zone_formation_at=deriv["zone_formation_at"],
                           order_available_at=deriv["order_available_at"])
                st.candidato = None
                # CF-40(b): orden creada EN la vela del deadline no queda viva.
                if T >= cand["deadline_close"]:
                    self._emit("confirmada_sin_fill", T, mercado,
                               finalized_at=fin, id=oid, motivo="deadline")
                    st.orden = None
                    st.estado = "flat"
                    return
                st.orden = {"order_id": oid, "candidate_id": cand["candidate_id"],
                            "E": E, "S": S, "T": Tp, "largo": largo,
                            "dir": cand["dir"],
                            "deadline_close": cand["deadline_close"]}
                st.estado = "orden_viva"
                return
            # El par existe pero no es operable: el candidato sigue vivo.

        # (c) DEADLINE.
        if T >= cand["deadline_close"]:
            self._emit("candidato_expirado", T, mercado, finalized_at=fin,
                       id=cand["candidate_id"], motivo="deadline")
            st.candidato = None
            st.estado = "flat"
            return

        # (d) DIRECCIÓN.
        if calc["direccion"] != cand["dir"]:
            self._emit("candidato_expirado", T, mercado, finalized_at=fin,
                       id=cand["candidate_id"], motivo="direccion")
            st.candidato = None
            st.estado = "flat"

    def _par_ganador(self, ep: list[dict], k: int, cand: dict):
        """CF-39.2: primer iBOS posterior a `j_toma` (≤48 velas del toque)
        que TENGA zona derivada. Devuelve (E, S, deriv) o None."""
        largo = cand["largo"]
        j_toque = cand["j_toque"]
        # CF-39 exige los swings INT CAUSALES de la ÉPOCA: no se recorta la
        # historia previa al toque (un recorte cambiaba j_toma, reiniciaba el
        # estado de bos_events y podía alterar qué iBOS resulta primero).
        seg = ep[:k]
        if len(seg) < 3 * INT_PIV:
            return None
        off = j_toque
        swings = self._swings_m15(cand["mercado"], seg)
        limite = min(len(seg), off + VENTANA_IBOS_M15 + 1)
        j_toma = P.primera_toma(seg, off, limite, largo, swings_int=swings)
        if j_toma is None:
            return None
        eventos = [e for e in P.bos_events(seg, INT_PIV, swings=swings)
                   if e["dir"] == ("up" if largo else "down")
                   and e["j"] > j_toma and e["j"] <= off + VENTANA_IBOS_M15]
        for e in eventos:                          # orden creciente de j
            deriv = P.zona_derivada(seg, e["j"], largo, DUR_M15,
                                    swings_int=swings)
            if deriv is None:
                continue                            # se descarta y sigue
            E = Q(deriv["hi"] if largo else deriv["lo"])
            extremo = min(v["l"] for v in seg[e["j"]:]) if largo \
                else max(v["h"] for v in seg[e["j"]:])
            S = Q(extremo * (1 - SL_BUFFER)) if largo \
                else Q(extremo * (1 + SL_BUFFER))
            return E, S, deriv
        return None

    def _swings_m15(self, mercado: str, seg: list[dict]):
        """Swings INT del prefijo `seg` de la época. Se obtienen filtrando los
        de la serie completa por `confirm_idx` (equivalencia exacta,
        `primitives.swings_prefijo`) para no rehacer O(n·L) por lote."""
        alm = self.m15.get(mercado)
        if alm is None or not alm.velas:
            return P.swing_points(seg, INT_PIV)
        ep0 = alm.epoca_de(int(seg[0]["t"]))
        if ep0 is None or ep0[0] is not seg[0]:
            return P.swing_points(seg, INT_PIV)
        cache = getattr(self, "_swm15", None)
        if cache is None:
            cache = self._swm15 = {}
        hit = cache.get(mercado)
        if hit is None or hit[0] is not ep0:
            hit = cache[mercado] = (ep0, P.swing_points(ep0, INT_PIV))
        return P.swings_prefijo(hit[1], len(seg))

    # --- Fase 8: corte ----------------------------------------------------
    def _fase8(self, T: int) -> None:
        if len(self.cierres) < CORTE_N_CIERRES:
            return
        semanas = {self._semana_iso(c["t"]) for c in self.cierres}
        if len(semanas) < CORTE_MIN_SEMANAS_ISO:
            return
        self._cerrar("muestra", T)

    @staticmethod
    def _semana_iso(ms: int) -> tuple:
        import datetime
        d = datetime.datetime.utcfromtimestamp(ms / 1000).date()
        y, w, _ = d.isocalendar()
        return (y, w)

    def _cerrar_por_tiempo(self, T: int) -> None:
        self._cerrar("tiempo", min(T, T_CORTE))

    def _cerrar(self, motivo: str, T: int) -> None:
        if self.cortado:
            return
        for mercado in self.mercados:
            st = self.estados[mercado]
            if st.estado in ("posicion", "salida_detectada") and st.posicion:
                self._emit("abierta_al_corte", T, mercado,
                           id=st.posicion["trade_id"])
            elif st.estado == "candidato_vivo":
                pass                     # un candidato sin orden no se registra
            elif st.estado == "orden_viva" and st.orden:
                self._emit("orden_al_corte", T, mercado,
                           id=st.orden["order_id"])
        self.cortado = True
        self.motivo_corte = motivo
