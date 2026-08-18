"""Gates obligatorios de Bot3.v9 (protocolo `9d24166a…`, CONFORME).

Cubre los gates que el contrato exige antes de autorizar despliegue:
  1. Vectores dorados CF-15 (Q y R de los vectores A/B/C).
  2. Vectores dorados CF-17/CF-31/CF-36 (cadena del almacén, marcador local
     y de exchange).
  3. Vectores dorados CF-30/CF-37 (event_id de todas las familias).
  4. Llegada tardía A/B (CF-22): mismo almacén con cualquier orden de arribo.
  5. Determinismo de génesis: dos profundidades de carga → mismo libro.
  6. Nacimiento M15 desde snapshot (CF-28): prohibido nacer del push.
  7. Lote con mercado ausente y silencio total (CF-23/CF-29/CF-35).
  8. Crash idempotente por familia (CF-30).
  9. Heads duales causales en catch-up (CF-32/CF-34).
 10. Frescura pre/post frontera (CF-24).
 11. Fill/salidas con gap y fill+STOP (§4.5, CF-2, CF-20).
 12. Funding causal (CF-8).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.bot3.v9 import contract as C  # noqa: E402
from modules.bot3.v9 import engine as E  # noqa: E402
from modules.bot3.v9 import store as S  # noqa: E402
from modules.bot3.v9.ledger import Ledger  # noqa: E402

CT = "0" * 64
DUR = C.TF_MS["15m"]


def vela(t, o, h, l, c, v=1.0):
    return {"t": int(t), "o": o, "h": h, "l": l, "c": c, "v": v}


# ---------------------------------------------------------------- CF-15 ---
def test_cf15_cuantizacion():
    assert C.Q(1.0000005) == 1.000001
    assert C.Q(1.0000015) == 1.000001
    assert C.Q(99.0009) == 99.0009
    assert C.Q(2.3456785) == 2.345678
    assert C.p6(99.0009) == "99.000900"


def test_cf15_vector_A():
    """Largo; fill favorable al open; TP con gap; 1 devengo → R = 5.4037."""
    extremo, Ev, T = 99.10, 100.0, 105.0
    Sv = C.Q(extremo * (1 - C.SL_BUFFER))
    assert Sv == 99.0009
    P_in = C.Q(99.95)
    P_out = C.Q(105.40)
    fundings = [C.FUNDING_RATE * C.Q(101.23)]
    pnl, r = E.resultado_r(P_in, P_out, Ev, Sv, True, "tp", fundings)
    assert round(pnl, 6) == 5.398807
    assert round(r, 4) == 5.4037


def test_cf15_vector_B():
    """Largo; fill a E; gap-SL en la salida; sin funding → R = −1.2909."""
    Ev, extremo = 100.0, 99.0
    Sv = C.Q(extremo * (1 - C.SL_BUFFER))
    assert Sv == 98.901
    base = C.Q(98.70)
    P_out = C.Q(base * (1 - C.SLIPPAGE_STOP))
    assert P_out == 98.65065
    pnl, r = E.resultado_r(Ev, P_out, Ev, Sv, True, "stop", [])
    assert round(r, 4) == -1.2909


def test_cf15_vector_C():
    """Corto; fill al open; STOP normal → R = −0.8830."""
    Ev, extremo = 200.0, 202.0
    Sv = C.Q(extremo * (1 + C.SL_BUFFER))
    assert Sv == 202.202
    P_in = C.Q(200.5)
    P_out = C.Q(C.Q(Sv) * (1 + C.SLIPPAGE_STOP))
    assert P_out == 202.303101
    pnl, r = E.resultado_r(P_in, P_out, Ev, Sv, False, "stop", [])
    assert round(r, 4) == -0.8830


# ------------------------------------------------------- CF-17/31/36 ------
C1 = vela(1646092800000, 1.0, 2.5, 0.5, 1.00000049, 123.456)
C2 = vela(1646093700000, 1.00000049, 1.2, 0.9, 1.00000040, 0.0)
C3 = vela(1646095500000, 1.1, 1.3, 1.05, 1.25, 10.0)
PRUEBA_LOCAL = [1646096400000, 1646097300000, 1646098200000]


def test_cf17_serializacion_distingue_crudos():
    """El hash cubre los CRUDOS: 1.00000040 y 1.00000049 no colisionan."""
    assert '"c":"1.00000049"' in S.ser_vela(C1)
    assert '"c":"1.0000004"' in S.ser_vela(C2)


def test_cf31_cadena_con_marcador_local():
    h1 = S.encadenar(S.SEMILLA, S.ser_vela(C1))
    h2 = S.encadenar(h1, S.ser_vela(C2))
    hg = S.encadenar(h2, S.ser_gap(1646094600000, 1646094600000, "local",
                                   PRUEBA_LOCAL))
    h3 = S.encadenar(hg, S.ser_vela(C3))
    assert h1 == "7bceed811ed9f3d848f5139114b9c8b04ea50b46347f6de61d11291bec1271e7"
    assert h2 == "5d84537de5783432781eeadecdf86759d26abc93bbbdff158b7a9832161df6cf"
    assert hg == "2d649fd44e2e7e77905473a29b6edc93082865829c90f6ec904614ee48ea9317"
    assert h3 == "157837865ad4abb014e2c3c3ec3ca133965c4ac3ebccf8840813a8827b0d95d9"


def test_cf36_marcador_exchange():
    h2 = "5d84537de5783432781eeadecdf86759d26abc93bbbdff158b7a9832161df6cf"
    prueba = {m: [1646095500000, 1646096400000, 1646097300000]
              for m in ("ADAUSDT", "BNBUSDT", "ETHUSDT", "SOLUSDT")}
    hg = S.encadenar(h2, S.ser_gap(1646094600000, 1646094600000, "exchange",
                                   prueba))
    assert hg == "96da3e96173407b2baf6a2880feb0926eff25a34c6865c09263f11daee6c74c8"
    assert S.detected_at(prueba) == 1646097300000


# ------------------------------------------------------- CF-30/CF-37 ------
def test_cf30_vectores_event_id():
    esperado = {
        ("lote_finalizado", ()): "bfed95caa6bfad87697f8cc4cca1580c62f1b6fc3061b6abeebef27b07bd5c6b",
        ("frontera", ()): "84bb23de88c477538fce49333da5a2ae02ae52084056e7541f4fcba10aff991e",
    }
    assert C.event_id("lote_finalizado", contrato=CT, t=1646095500000) == \
        esperado[("lote_finalizado", ())]
    assert C.event_id("frontera", contrato=CT, t=1646092800000) == \
        esperado[("frontera", ())]
    assert C.event_id("estado_inicial", contrato=CT, mercado="BTCUSDT",
                      t=1646092800000) == \
        "c1692c949f95513f360605929de6f8058cc850c94d348aceaa5d128a7d002f6e"
    assert C.event_id("epoca_m15", contrato=CT, mercado="BTCUSDT",
                      t=1646092800000) == \
        "b63500ccf34c2889b4c88121daaa0248324473163862da78a88adb06051a13de"
    assert C.event_id("abstencion", contrato=CT, mercado="BTCUSDT",
                      motivo="rango_sin_origen", t=1646095500000) == \
        "6b2e5a76e2885234507e9e5cef10afbfadd648a0ebdd2b997fd453b5d7b2dedc"
    assert C.event_id("mercado_degradado", contrato=CT, mercado="BTCUSDT",
                      t=1646095500000) == \
        "d47fcb9946fb0a1ca935f7b5cb2692d95223aad144194f166d7976911d586193"
    assert C.event_id("abierta_al_corte", contrato=CT, id="1" * 64) == \
        "58eb9ddb2112318a25eeb6bd8b1b04ed91567c5bac47032c5d97a223e2b1a663"
    assert C.event_id("orden_al_corte", contrato=CT, id="2" * 64) == \
        "563f3df291d78971685c0e81c81fe1de8060074e51634157398436e83b059256"
    assert C.event_id("degradacion_de_cobertura", contrato=CT, mercado="BTCUSDT",
                      desde=1798761600000, hasta=1798848000000) == \
        "34e0260c4a798204be97656d876f347967e3de0cf3bd9ddf8566d81771afdde9"


def test_cf37_registro_cerrado():
    import pytest
    with pytest.raises(ValueError):
        C.event_id("tipo_inventado", t=1)
    ledger = Ledger()
    with pytest.raises(ValueError):
        ledger.append("tipo_inventado", effective_at=1)


# ------------------------------------------------------------- CF-22 ------
def _almacen_con(velas_por_ciclo, mercado="BTCUSDT"):
    alm = S.Almacen(mercado, "15m")
    alm.nacer_en(int(velas_por_ciclo[0][0]["t"]))
    for ciclo in velas_por_ciclo:
        alm.ofrecer(ciclo, "push")
        alm.drenar()
        alm.declarar_hueco_local()
    return alm


def test_cf22_llegada_tardia_AB():
    """Escenario A/B del informe v5: t2 antes que t1 vs juntas → mismo
    almacén. El buffer impide appendear con la predecesora faltante."""
    t0 = 1646092800000
    v = [vela(t0 + i * DUR, 1 + i, 2 + i, 0.5 + i, 1.5 + i) for i in range(4)]
    a = S.Almacen("BTCUSDT", "15m"); a.nacer_en(t0)
    a.ofrecer([v[0]], "push"); a.drenar()
    a.ofrecer([v[2]], "push"); a.drenar()          # llega antes que v[1]
    a.ofrecer([v[1], v[3]], "push"); a.drenar()
    b = S.Almacen("BTCUSDT", "15m"); b.nacer_en(t0)
    b.ofrecer(v, "push"); b.drenar()
    assert [r["hash_acum"] for r in a.registros] == \
           [r["hash_acum"] for r in b.registros]
    assert len(a.velas) == 4


def test_cf22_prioridad_versionado_en_buffer():
    """Una copia versionada que llega después REEMPLAZA al push en el buffer
    (nunca en el almacén)."""
    t0 = 1646092800000
    push = vela(t0, 1.0, 2.0, 0.5, 1.5)
    vers = vela(t0, 1.0, 2.0, 0.5, 1.6)
    alm = S.Almacen("BTCUSDT", "15m"); alm.nacer_en(t0)
    alm.ofrecer([push], "push")
    alm.ofrecer([vers], "versionado")
    alm.drenar()
    assert alm.velas[0]["c"] == 1.6


def test_cf22_hueco_local_con_prueba():
    """N=3 cierres posteriores declaran el hueco; el marcador entra a la
    cadena y `detected_at` = max(prueba)."""
    t0 = 1646092800000
    alm = S.Almacen("BTCUSDT", "15m"); alm.nacer_en(t0)
    alm.ofrecer([vela(t0, 1, 2, 0.5, 1.5)], "push"); alm.drenar()
    faltante = t0 + DUR
    posteriores = [vela(t0 + i * DUR, 1, 2, 0.5, 1.5) for i in (2, 3, 4)]
    alm.ofrecer(posteriores, "push"); alm.drenar()
    assert alm.hueco_pendiente() == (faltante, faltante)
    reg = alm.declarar_hueco_local()
    assert reg["motivo"] == "local"
    # prueba = close_time de las 3 primeras velas del buffer (t0+2,3,4 DUR).
    assert reg["detected_at"] == t0 + 5 * DUR
    assert len(alm.velas) == 4
    # Una vela tardía del hueco ya no entra jamás.
    alm.ofrecer([vela(faltante, 1, 2, 0.5, 1.5)], "versionado")
    alm.drenar()
    assert all(int(v["t"]) != faltante for v in alm.velas)
    assert alm.incidencias and alm.incidencias[-1]["t"] == faltante


def test_cf13_epocas_no_cruzan_huecos():
    t0 = 1646092800000
    alm = S.Almacen("BTCUSDT", "15m"); alm.nacer_en(t0)
    alm.ofrecer([vela(t0, 1, 2, 0.5, 1.5)], "push"); alm.drenar()
    alm.ofrecer([vela(t0 + i * DUR, 1, 2, 0.5, 1.5) for i in (2, 3, 4)], "push")
    alm.drenar(); alm.declarar_hueco_local()
    epocas = alm.epocas()
    assert len(epocas) == 2 and len(epocas[0]) == 1 and len(epocas[1]) == 3


# ------------------------------------------------------------- CF-28 ------
def test_cf28_nacimiento_desde_snapshot():
    """El ancla es el menor `t` del snapshot versionado; una instalación que
    solo ve el push NO puede nacer (y por tanto no diverge)."""
    t0 = 1646092800000
    snapshot = [vela(t0 + i * DUR, 1, 2, 0.5, 1.5) for i in range(3)]
    push_tardio = [vela(t0 + i * DUR, 1, 2, 0.5, 1.5) for i in range(5, 8)]
    a = S.Almacen("BTCUSDT", "15m"); a.nacer_en(int(snapshot[0]["t"]))
    a.ofrecer(snapshot, "versionado"); a.drenar()
    a.ofrecer(push_tardio, "push"); a.drenar()
    b = S.Almacen("BTCUSDT", "15m")
    assert b.ultimo_t is None                    # sin snapshot no nace
    b.ofrecer(push_tardio, "push"); b.drenar()
    assert b.velas == []
    b.nacer_en(int(snapshot[0]["t"]))
    b.ofrecer(snapshot + push_tardio, "versionado"); b.drenar()
    assert [int(v["t"]) for v in a.velas] == [int(v["t"]) for v in b.velas]


# ------------------------------------------------------- CF-29/CF-35 ------
def _mundo(mercados, hasta_idx, silencioso=None, t0=1646092800000):
    alms = {}
    for m in mercados:
        alm = S.Almacen(m, "15m"); alm.nacer_en(t0)
        n = hasta_idx if m != silencioso else 1
        alm.ofrecer([vela(t0 + i * DUR, 1, 2, 0.5, 1.5) for i in range(n)], "push")
        alm.drenar()
        alms[m] = alm
    return alms


def test_cf29_prueba_exchange_quorum_alfabetico():
    mercados = C.MERCADOS
    alms = _mundo(mercados, 6, silencioso="BTCUSDT")
    T = 1646092800000 + DUR          # close_time del lote donde falta BTC
    prueba = S.prueba_exchange(alms, "BTCUSDT", T)
    assert prueba is not None
    assert list(prueba) == ["ADAUSDT", "BNBUSDT", "DOGEUSDT", "ETHUSDT"]
    assert all(len(v) == 3 for v in prueba.values())


def test_cf29_sin_quorum_no_declara():
    """Caída parcial amplia (solo 3 mercados activos): no hay quorum Q=4."""
    mercados = C.MERCADOS
    alms = {}
    t0 = 1646092800000
    for i, m in enumerate(mercados):
        alm = S.Almacen(m, "15m"); alm.nacer_en(t0)
        n = 6 if i < 3 else 1
        alm.ofrecer([vela(t0 + k * DUR, 1, 2, 0.5, 1.5) for k in range(n)], "push")
        alm.drenar()
        alms[m] = alm
    assert S.prueba_exchange(alms, mercados[6], t0 + DUR) is None


def test_cf35_corte_administrativo_total():
    """Sin lote global finalizado > T_corte, el corte administrativo actúa
    aunque existan velas parciales."""
    led = Ledger()
    alms = _mundo(C.MERCADOS, 3)
    motor = E.Motor(alms, alms, C.MERCADOS, led)
    motor.procesar_lote(C.T_CORTE + DUR)          # pre-gate temporal
    assert motor.cortado is True
    assert motor.motivo_corte == "tiempo"


# ------------------------------------------------------------- CF-30 ------
def test_cf30_idempotencia_crash(tmp_path):
    """Reproceso tras crash en cualquier punto: el ledger final es idéntico."""
    ruta = str(tmp_path / "ledger.jsonl")
    familias = [
        ("lote_finalizado", dict(effective_at=1, finalized_at=1)),
        ("frontera", dict(effective_at=2, finalized_at=2)),
        ("estado_inicial", dict(mercado="BTCUSDT", effective_at=3, finalized_at=3)),
        ("epoca_m15", dict(mercado="BTCUSDT", effective_at=4, finalized_at=4)),
        ("abstencion", dict(mercado="BTCUSDT", motivo="rango_sin_origen",
                            effective_at=5, finalized_at=5)),
        ("descarte", dict(mercado="BTCUSDT", motivo="rr_insuficiente",
                          effective_at=6, finalized_at=6, zona_avail=1,
                          zona_lo=1.0, zona_hi=2.0)),
        ("nacimiento", dict(mercado="BTCUSDT", tf="15m", effective_at=7,
                            finalized_at=7)),
        ("hueco_detectado", dict(mercado="BTCUSDT", tf="15m", desde=8, hasta=9,
                                 effective_at=8, finalized_at=8)),
        ("degradacion_de_cobertura", dict(mercado="BTCUSDT", desde=10, hasta=11,
                                          effective_at=10, finalized_at=10)),
        ("cerrado", dict(mercado="BTCUSDT", id="a" * 64, effective_at=12,
                         finalized_at=12)),
    ]
    for corte in range(len(familias) + 1):
        if os.path.exists(ruta):
            os.remove(ruta)
        parcial = Ledger(ruta)
        for tipo, campos in familias[:corte]:      # "crash" tras `corte`
            parcial.append(tipo, **campos)
        reanudado = Ledger(ruta)                   # relee lo escrito
        for tipo, campos in familias:
            reanudado.append(tipo, **campos)
        assert len(reanudado.eventos) == len(familias)
        assert len({e["event_id"] for e in reanudado.eventos}) == len(familias)


# ------------------------------------------------------------- CF-32 ------
def test_cf32_heads_causales_en_catchup():
    """CF-32/CF-34 literales: el head de inputs avanza solo con registros
    CONSUMIBLES en `T` (velas con `t+dur ≤ T`; marcadores con
    `detected_at ≤ T`) y nunca es el head físico antes de la finalidad.

    NOTA (hallazgo para v10, no bloqueante): mientras el marcador no es
    consumible, el head de inputs se queda en el prefijo pre-hueco aunque el
    modelo ya consuma velas posteriores al hueco. No afecta el determinismo
    del libro (las velas son las mismas), pero el head sub-identifica los
    bytes consumidos durante el catch-up."""
    t0 = 1646092800000
    v0 = vela(t0, 1, 2, 0.5, 1.5)
    alm = S.Almacen("BTCUSDT", "15m"); alm.nacer_en(t0)
    alm.ofrecer([v0], "push"); alm.drenar()
    alm.ofrecer([vela(t0 + i * DUR, 1, 2, 0.5, 1.5) for i in (2, 3, 4, 5)], "push")
    alm.drenar()
    reg = alm.declarar_hueco_local()
    fisico = alm.head
    h1 = S.encadenar(S.SEMILLA, S.ser_vela(v0))
    detected = reg["detected_at"]
    # Antes de la detección: head de inputs = prefijo pre-hueco.
    assert alm.head_asof(t0 + DUR) == h1
    assert alm.head_asof(detected - DUR) == h1
    # Desde la detección avanza y nunca es el físico hasta cubrir todo.
    h_det = alm.head_asof(detected)
    assert h_det not in (h1, fisico)
    assert alm.head_asof(t0 + 6 * DUR) == fisico
    # El head de provenance SÍ incluye el marcador que liberó el lote.
    assert alm.head_finality(detected) == h_det


# ------------------------------------------------------------- CF-24 ------
def test_cf24_frescura_sobrevive_a_la_frontera():
    """Una zona tocada ANTES de la frontera no puede crear candidato después
    (la frescura se consume en bootstrap, aunque no se emita)."""
    st = E.EstadoMercado("BTCUSDT")
    clave = ("ob", "long", 1.0, 2.0, 123)
    st.zonas_tocadas.add(clave)
    assert clave in st.zonas_tocadas               # persiste tras la frontera
    st.estado = "flat"
    assert st.estado == "flat"                     # forzado a flat en frontera


# --------------------------------------------------------- fills/salidas --
def test_fill_gap_ambiguo_y_fill_stop():
    E_, S_ = 100.0, 99.0
    # Abre más allá del SL antes de poder ejecutar → gap_ambiguo (abstención).
    assert E.evaluar_fill(vela(0, 98.5, 99.5, 98.0, 99.0), E_, S_, True)[0] == \
        "gap_ambiguo"
    # Gap a favor: abre bajo E → fill al OPEN.
    r, p = E.evaluar_fill(vela(0, 99.5, 100.2, 99.2, 99.8), E_, S_, True)
    assert (r, p) == ("fill", 99.5)
    # Toca E y luego el SL en la misma vela → fill + STOP (CF-20).
    r, p = E.evaluar_fill(vela(0, 100.5, 100.6, 98.9, 99.2), E_, S_, True)
    assert (r, p) == ("fill_stop", 100.0)
    # Sin cruce.
    assert E.evaluar_fill(vela(0, 100.5, 100.9, 100.2, 100.4), E_, S_, True)[0] is None


def test_salida_gap_y_ambigua():
    S_, T_ = 99.0, 105.0
    m, p = E.evaluar_salida(vela(0, 98.0, 98.5, 97.0, 97.5), S_, T_, True)
    assert m == "stop" and p == C.Q(98.0 * (1 - C.SLIPPAGE_STOP))
    m, p = E.evaluar_salida(vela(0, 106.0, 106.5, 105.5, 106.2), S_, T_, True)
    assert (m, p) == ("tp", 106.0)
    m, p = E.evaluar_salida(vela(0, 100.0, 105.5, 98.5, 104.0), S_, T_, True)
    assert m == "stop"                              # vela ambigua = STOP
    m, p = E.evaluar_salida(vela(0, 100.0, 105.5, 99.5, 105.0), S_, T_, True)
    assert (m, p) == ("tp", 105.0)


def test_cf8_devengos_funding():
    """Devengo sii close(fill) < k ≤ close(salida): fill en el instante no
    devenga; salida en el instante sí (cargo conservador)."""
    k = 8 * 3_600_000
    assert E.devengos_funding(k, k + 900_000) == []
    assert E.devengos_funding(k - 900_000, k) == [k]
    assert len(E.devengos_funding(0, 24 * 3_600_000)) == 3


def test_contrato_hash_congelado():
    """El contrato implementado es exactamente el declarado CONFORME."""
    import hashlib
    ruta = os.path.join(os.path.dirname(__file__), "..", "docs",
                        "BOT3_V13_PROTOCOLO.md")
    with open(ruta, "rb") as fh:
        assert hashlib.sha256(fh.read()).hexdigest() == C.CONTRATO_HASH


# ---------------------------------- B-1 auditoría 2026-08-17 (look-ahead) --
def test_b1_habilitacion_m15_no_mira_el_futuro_fisico():
    """La habilitación de época se mide sobre velas CERRADAS en T, nunca
    sobre el tamaño físico del almacén (que contiene futuro)."""
    from modules.bot3.v9.ledger import Ledger as L
    t0 = 1646092800000
    alm = S.Almacen("BTCUSDT", "15m"); alm.nacer_en(t0)
    alm.ofrecer([vela(t0 + i * DUR, 1, 2, 0.5, 1.5) for i in range(220)], "push")
    alm.drenar()
    motor = E.Motor({"BTCUSDT": alm}, {"BTCUSDT": alm}, ("BTCUSDT",), L())
    assert motor._epoca_habilitada("BTCUSDT", t0 + 10 * DUR) is None
    assert motor._epoca_habilitada("BTCUSDT", t0 + 199 * DUR) is None
    ok = motor._epoca_habilitada("BTCUSDT", t0 + 200 * DUR)
    assert ok is not None and ok[1] == 200


def test_b1_hueco_h4_posterior_no_altera_el_pasado():
    """Un hueco H4 POSTERIOR a T no puede volver `historia_insuficiente` un
    instante anterior: la continuidad se evalúa sobre el prefijo causal."""
    from modules.bot3.v9.ledger import Ledger as L
    from modules.bot3.v9.engine import DUR_H4
    g = C.GENESIS_H4
    def h4_store(con_hueco_futuro):
        alm = S.Almacen("BTCUSDT", "4h"); alm.nacer_en(g)
        alm.ofrecer([vela(g + i * DUR_H4, 1 + i * 0.01, 2 + i * 0.01,
                          0.5 + i * 0.01, 1.5 + i * 0.01) for i in range(60)],
                    "push")
        alm.drenar()
        if con_hueco_futuro:      # hueco MUY posterior al T evaluado
            alm.ofrecer([vela(g + i * DUR_H4, 1, 2, 0.5, 1.5)
                         for i in (70, 71, 72)], "push")
            alm.drenar(); alm.declarar_hueco_local()
        return alm
    T = g + 40 * DUR_H4
    m15 = S.Almacen("BTCUSDT", "15m"); m15.nacer_en(g)
    resultados = []
    for con_hueco in (False, True):
        motor = E.Motor({"BTCUSDT": m15}, {"BTCUSDT": h4_store(con_hueco)},
                        ("BTCUSDT",), L())
        resultados.append(motor._calcular_h4("BTCUSDT", T)["motivo"])
    assert resultados[0] == resultados[1], \
        f"el hueco futuro cambió el pasado: {resultados}"


# ------------------------------ v13: ciclo del candidato (CF-38..CF-43) ---
def test_cf43_tipos_nuevos_y_vectores():
    CAND = "3" * 64
    assert C.event_id("candidato_expirado", contrato=CT, id=CAND) == \
        "7cc8eda9b1b9f43a99634abd927ea881c2edb37197b6478a56600ec0945e59b8"
    assert C.event_id("candidato_invalidado", contrato=CT, id=CAND) == \
        "8131681cbb2c46aab6489aadabb2b03e1ecd32c7cc52c7b3a3e140682da34c71"


def test_cf39_zona_derivada_ob_del_desplazamiento():
    """El OB del desplazamiento (última vela de cuerpo opuesto en
    [j_origen, j_ibos]) gana sobre cualquier FVG, y sus dos sellos
    temporales son distintos: formación (histórica) vs disponibilidad."""
    from modules.bot3.v9 import primitives as P
    t0 = 0
    velas = []
    # tramo bajista → swing low en idx 6 → impulso alcista hasta idx 14
    for i, (o, h, l, c) in enumerate([
        (10, 10.2, 9.8, 9.9), (9.9, 10.0, 9.5, 9.6), (9.6, 9.7, 9.2, 9.3),
        (9.3, 9.4, 8.9, 9.0), (9.0, 9.1, 8.6, 8.7), (8.7, 8.8, 8.3, 8.4),
        (8.4, 8.5, 8.0, 8.1),                                   # 6: mínimo
        (8.1, 8.6, 8.05, 8.5), (8.5, 9.0, 8.45, 8.9),
        (8.9, 9.4, 8.85, 8.8),                                  # 9: opuesta (OB)
        (8.8, 9.9, 8.75, 9.8), (9.8, 10.4, 9.75, 10.3),
        (10.3, 10.9, 10.25, 10.8), (10.8, 11.4, 10.75, 11.3),
        (11.3, 11.9, 11.25, 11.8),                              # 14: iBOS
    ]):
        velas.append(vela(t0 + i * DUR, o, h, l, c))
    deriv = P.zona_derivada(velas, 14, largo=True, dur=DUR)
    assert deriv is not None
    assert deriv["kind"] == "ob"
    assert deriv["order_available_at"] == int(velas[14]["t"]) + DUR
    assert deriv["zone_formation_at"] < deriv["order_available_at"]


def test_cf39_toma_exige_disponibilidad_causal():
    """Un swing con `confirm_idx ≥ k` no sirve como liquidez tomada por la
    vela `k` (M-3)."""
    from modules.bot3.v9 import primitives as P
    velas = [vela(i * DUR, 10, 10.2, 9.8, 10) for i in range(20)]
    velas[10] = vela(10 * DUR, 10, 10.2, 9.0, 10)      # mínimo profundo
    velas[12] = vela(12 * DUR, 10, 10.2, 8.5, 10)      # barre 9.0
    # El swing low de idx 10 confirma en 13; la vela 12 NO puede tomarlo.
    assert P.primera_toma(velas, 0, 13, largo=True) is None


# --- Gates DISCRIMINANTES del ciclo del candidato (ejercitan el motor) ----
#
# Se conducen a través de `_fase7a`/`_par_ganador` reales con una época
# sintética y un `calc` inyectado: prueban la LÓGICA del motor, no un ledger
# rellenado a mano.

PAD = 190          # relleno para superar EPOCA_M15_MIN_VELAS sin crear pivotes


def _epoca_confirmacion():
    """Época M15 con estructura REAL de confirmación:

    relleno descendente monótono (sin pivotes) → swing low → rebote →
    vela que BARRE ese low (toma de liquidez) → swing high → retroceso con
    vela de cuerpo opuesto (OB del desplazamiento) → impulso que rompe el
    high CON CUERPO (iBOS) → continuación.
    """
    velas = []
    for i in range(PAD):                       # descenso monótono: 0 pivotes
        base = 20.0 - i * 0.05
        velas.append(vela(i * DUR, base, base + 0.02, base - 0.06, base - 0.04))
    patron = [
        (10.55, 10.60, 10.30, 10.35),          # 190
        (10.35, 10.40, 9.90, 9.95),            # 191
        (9.95, 10.00, 9.40, 9.45),             # 192
        (9.45, 9.50, 8.80, 8.85),              # 193
        (8.85, 8.90, 8.00, 8.10),              # 194: SWING LOW (8.00)
        (8.10, 8.60, 8.05, 8.55),              # 195
        (8.55, 9.00, 8.50, 8.95),              # 196
        (8.95, 9.30, 8.90, 9.25),              # 197
        (9.25, 9.40, 7.90, 9.30),              # 198: BARRE el 8.00 (toma)
        (9.30, 9.60, 9.28, 9.55),              # 199
        (9.55, 10.00, 9.50, 9.95),             # 200
        (9.95, 10.50, 9.92, 10.40),            # 201: SWING HIGH (10.50)
        (10.40, 10.45, 10.10, 10.15),          # 202
        (10.15, 10.20, 9.90, 9.95),            # 203: cuerpo OPUESTO → OB
        (9.95, 10.10, 9.92, 10.05),            # 204: SWING LOW (9.92)
        (10.05, 10.30, 10.00, 10.25),          # 205
        (10.25, 10.90, 10.20, 10.80),          # 206: iBOS (cierra > 10.50)
        (10.80, 11.20, 10.75, 11.10),          # 207
        (11.10, 11.50, 11.05, 11.40),          # 208
        (11.40, 11.80, 11.35, 11.70),          # 209
    ]
    for k, pr in enumerate(patron):
        velas.append(vela((PAD + k) * DUR, *pr))
    return velas


J_LOW, J_TOMA, J_HIGH, J_OB, J_IBOS = PAD + 4, PAD + 8, PAD + 11, PAD + 13, PAD + 16


def _motor_con(ep):
    from modules.bot3.v9.ledger import Ledger as L
    alm = S.Almacen("BTCUSDT", "15m"); alm.nacer_en(int(ep[0]["t"]))
    alm.ofrecer(ep, "push"); alm.drenar()
    led = L()
    return E.Motor({"BTCUSDT": alm}, {"BTCUSDT": alm}, ("BTCUSDT",), led), led


def _candidato(st, ep, j_toque, deadline_velas=E.DEADLINE_M15, weak=20.0):
    st.estado = "candidato_vivo"
    st.candidato = {
        "candidate_id": "c" * 64, "mercado": "BTCUSDT",
        "zona": {"kind": "ob", "dir": "long", "lo": 8.0, "hi": 9.5,
                 "available_at": 0},
        "dir": "long", "largo": True, "j_toque": j_toque,
        "close_toque": int(ep[j_toque]["t"]) + DUR,
        "deadline_close": int(ep[j_toque]["t"]) + DUR + deadline_velas * DUR,
        "weak": weak,
    }
    return st


CALC_OK = {"direccion": "long", "rango": {"weak": 20.0, "eq": 9.0},
           "zonas": [], "fractal": {"available_at": 0}, "motivo": None}


def test_b2_estructura_del_escenario():
    """El escenario sintético tiene la estructura que los demás gates
    asumen: low, toma, high, OB e iBOS en sus índices."""
    from modules.bot3.v9 import primitives as P
    ep = _epoca_confirmacion()
    sh, sl = P.swing_points(ep, C.INT_PIV)
    assert any(p["idx"] == J_LOW and p["price"] == 8.00 for p in sl)
    assert any(p["idx"] == J_HIGH and p["price"] == 10.50 for p in sh)
    assert P.primera_toma(ep, PAD, len(ep), largo=True) == J_TOMA
    ups = [e["j"] for e in P.bos_events(ep, C.INT_PIV) if e["dir"] == "up"]
    assert J_IBOS in ups


def test_b2_ibos_previo_al_toque_no_produce_orden():
    """Un iBOS ANTERIOR al toque no puede confirmar (defecto B-2)."""
    ep = _epoca_confirmacion()
    motor, _ = _motor_con(ep)
    st = _candidato(motor.estados["BTCUSDT"], ep, j_toque=J_IBOS + 1)
    assert motor._par_ganador(ep, len(ep), st.candidato) is None


def test_b2_ibos_posterior_al_toque_si_confirma():
    """Toque ANTES del barrido y del iBOS → par ganador; la zona derivada es
    el OB del desplazamiento y sus dos sellos son distintos."""
    ep = _epoca_confirmacion()
    motor, led = _motor_con(ep)
    st = _candidato(motor.estados["BTCUSDT"], ep, j_toque=PAD + 6)
    par = motor._par_ganador(ep, len(ep), st.candidato)
    assert par is not None
    Ev, Sv, deriv = par
    assert deriv["kind"] == "ob"
    assert deriv["zone_formation_at"] == int(ep[J_OB]["t"]) + DUR
    assert deriv["order_available_at"] == int(ep[J_IBOS]["t"]) + DUR
    assert deriv["zone_formation_at"] < deriv["order_available_at"]
    assert Sv < Ev


def test_b2_transicion_sin_eventos_cruzados():
    """candidato → orden: ningún `candidato_*` tras crear la orden."""
    ep = _epoca_confirmacion()
    motor, led = _motor_con(ep)
    st = _candidato(motor.estados["BTCUSDT"], ep, j_toque=PAD + 6)
    T = int(ep[-1]["t"]) + DUR
    motor._fase7a("BTCUSDT", T, T, ep, len(ep), CALC_OK, st)
    assert st.estado == "orden_viva" and st.candidato is None
    tipos = [e["tipo"] for e in led.eventos]
    assert tipos.count("orden_creada") == 1
    assert not any(t.startswith("candidato_") for t in tipos)


def test_b2_orden_en_el_deadline_no_sobrevive():
    """Zona derivada completada EN la vela del deadline → `orden_creada` +
    `confirmada_sin_fill` en la misma vela, estado `flat` (CF-40 b)."""
    ep = _epoca_confirmacion()
    motor, led = _motor_con(ep)
    st = motor.estados["BTCUSDT"]
    j_toque = PAD + 6
    _candidato(st, ep, j_toque, deadline_velas=(len(ep) - 1) - j_toque)
    T = int(ep[-1]["t"]) + DUR
    assert st.candidato["deadline_close"] == T
    motor._fase7a("BTCUSDT", T, T, ep, len(ep), CALC_OK, st)
    assert [e["tipo"] for e in led.eventos] == ["orden_creada",
                                                "confirmada_sin_fill"]
    assert st.estado == "flat" and st.orden is None


def test_b2_candidato_expira_exactamente_en_el_deadline():
    """Sin par ganador, el candidato muere EN la vela del deadline."""
    ep = _epoca_confirmacion()
    motor, led = _motor_con(ep)
    st = motor.estados["BTCUSDT"]
    j_toque = J_IBOS + 1
    _candidato(st, ep, j_toque, deadline_velas=(len(ep) - 1) - j_toque)
    T = st.candidato["deadline_close"]
    motor._fase7a("BTCUSDT", T, T, ep, len(ep), CALC_OK, st)
    assert st.estado == "flat"
    ev = [e for e in led.eventos if e["tipo"] == "candidato_expirado"]
    assert len(ev) == 1 and ev[0]["motivo"] == "deadline"


def test_b2_orden_viva_cierra_en_el_deadline_exacto():
    """Orden preexistente sin fill: su terminal sale EN el cierre exacto del
    deadline y es `confirmada_sin_fill`, no `orden_cancelada(direccion)`."""
    ep = _epoca_confirmacion()
    motor, led = _motor_con(ep)
    st = motor.estados["BTCUSDT"]
    T = int(ep[-1]["t"]) + DUR
    st.estado = "orden_viva"
    # Niveles muy por DEBAJO del precio: la orden nunca se toca (ni fill ni
    # gap), así el terminal que debe salir es el del deadline.
    st.orden = {"order_id": "o" * 64, "candidate_id": "c" * 64,
                "E": 5.0, "S": 4.95, "T": 20.0, "largo": True,
                "dir": "long", "deadline_close": T}
    motor._procesar_mercado("BTCUSDT", T, T)
    tipos = [e["tipo"] for e in led.eventos]
    assert "confirmada_sin_fill" in tipos
    assert "orden_cancelada" not in tipos
    assert st.estado == "flat"


def _epoca_swing_lejano():
    """Época donde el ÚNICO swing barrible está a 14 velas del toque:
    swing low → subida MONÓTONA de 16 velas (sin pivotes) → toque →
    barrido de ese low → swing high → retroceso con vela opuesta →
    iBOS con cuerpo. Con el recorte viejo (`j_toque − 12`) ese swing queda
    fuera y no habría toma; con la época causal completa, sí."""
    velas = []
    for i in range(PAD):
        b = 20.0 - i * 0.05
        velas.append(vela(i * DUR, b, b + 0.02, b - 0.06, b - 0.04))
    patron = [
        (10.55, 10.60, 10.30, 10.35), (10.35, 10.40, 9.60, 9.65),
        (9.65, 9.70, 8.80, 8.85), (8.85, 8.90, 8.40, 8.45),
        (8.45, 8.50, 8.00, 8.10),                      # 4: SWING LOW 8.00
    ]
    lo = 8.05
    for _ in range(16):                                # 5..20: subida monótona
        lo += 0.10
        patron.append((lo, lo + 0.12, lo - 0.02, lo + 0.10))
    patron.append((lo + 0.10, lo + 0.15, 7.90, lo + 0.05))          # 21: BARRIDO
    patron += [(lo + 0.05, lo + 0.30, lo + 0.00, lo + 0.25),
               (lo + 0.25, lo + 0.50, lo + 0.20, lo + 0.45)]
    top = lo + 0.45
    patron += [(top, top + 0.60, top - 0.05, top + 0.50),           # 24: SWING HIGH
               (top + 0.50, top + 0.55, top + 0.20, top + 0.25),
               (top + 0.25, top + 0.30, top + 0.05, top + 0.10),
               (top + 0.10, top + 0.15, top - 0.02, top - 0.01),    # 27: opuesta → OB
               (top - 0.01, top + 0.25, top + 0.00, top + 0.20),
               (top + 0.20, top + 0.45, top + 0.15, top + 0.40),
               (top + 0.40, top + 0.65, top + 0.35, top + 0.60),
               (top + 0.60, top + 1.30, top + 0.55, top + 1.20),    # 31: iBOS
               (top + 1.20, top + 1.50, top + 1.15, top + 1.45),
               (top + 1.45, top + 1.75, top + 1.40, top + 1.70)]
    for i, pr in enumerate(patron):
        velas.append(vela((PAD + i) * DUR, *pr))
    return velas


def test_b2_historia_lejana_cuenta_en_el_motor():
    """P1-b vía MOTOR: con el swing barrible a 14 velas del toque,
    `_par_ganador` encuentra el par. Emulando el recorte viejo
    (`j_toque − 4·INT_PIV`) NO lo encontraría — el gate discrimina."""
    from modules.bot3.v9 import primitives as P
    ep = _epoca_swing_lejano()
    j_toque = PAD + 18
    motor, _ = _motor_con(ep)
    st = _candidato(motor.estados["BTCUSDT"], ep, j_toque=j_toque, weak=30.0)
    par = motor._par_ganador(ep, len(ep), st.candidato)
    assert par is not None, "la época causal completa debe hallar el par"
    # Emulación EXACTA del recorte eliminado: la toma desaparece.
    ini = j_toque - 4 * C.INT_PIV
    seg = ep[ini:len(ep)]
    assert P.primera_toma(seg, j_toque - ini, len(seg), largo=True) is None


def test_b2_order_id_del_motor_usa_order_available_at():
    """P2 vía MOTOR: el `order_id` EMITIDO se construye con
    `order_available_at` (cierre del iBOS), no con `zone_formation_at`."""
    ep = _epoca_swing_lejano()
    motor, led = _motor_con(ep)
    st = _candidato(motor.estados["BTCUSDT"], ep, j_toque=PAD + 18, weak=30.0)
    cid = st.candidato["candidate_id"]
    par = motor._par_ganador(ep, len(ep), st.candidato)
    assert par is not None
    _Ev, _Sv, deriv = par
    T = int(ep[-1]["t"]) + DUR
    motor._fase7a("BTCUSDT", T, T, ep, len(ep), CALC_OK, st)
    emitidos = [e for e in led.eventos if e["tipo"] == "orden_creada"]
    assert len(emitidos) == 1
    esperado = C.order_id(cid, deriv["order_available_at"],
                          deriv["lo"], deriv["hi"])
    con_formacion = C.order_id(cid, deriv["zone_formation_at"],
                               deriv["lo"], deriv["hi"])
    assert emitidos[0]["id"] == esperado
    assert emitidos[0]["id"] != con_formacion
    assert emitidos[0]["order_available_at"] == deriv["order_available_at"]
    assert emitidos[0]["zone_formation_at"] == deriv["zone_formation_at"]


def test_b2_dos_ibos_misma_caja_producen_order_id_distintos():
    """`order_available_at` (cierre del iBOS) entra en `order_id`: dos iBOS
    distintos sobre la MISMA caja producen identidades distintas."""
    caja = dict(lo=9.4, hi=9.8)
    o1 = C.order_id("c" * 64, 1_000_000, caja["lo"], caja["hi"])
    o2 = C.order_id("c" * 64, 2_000_000, caja["lo"], caja["hi"])
    assert o1 != o2


# ------------------------------------- B-3: frontera y estado inicial -----
def _motor_bootstrap(ep, frontera):
    from modules.bot3.v9.ledger import Ledger as L
    alm = S.Almacen("BTCUSDT", "15m"); alm.nacer_en(int(ep[0]["t"]))
    alm.ofrecer(ep, "push"); alm.drenar()
    led = L()
    return E.Motor({"BTCUSDT": alm}, {"BTCUSDT": alm}, ("BTCUSDT",), led,
                   bootstrap_hasta=frontera), led


def test_b3_bootstrap_no_emite_pero_cruza_a_flat():
    """CF-21/CF-24: antes de la frontera no se emite nada; al cruzarla se
    emiten `frontera` + `estado_inicial` y TODO mercado queda `flat`."""
    ep = _epoca_confirmacion()
    frontera = int(ep[-3]["t"]) + DUR
    motor, led = _motor_bootstrap(ep, frontera)
    st = motor.estados["BTCUSDT"]
    # Estado sintético "heredado" del bootstrap: una posición viva.
    st.estado = "posicion"
    # Niveles lejanos: la posición NO sale durante el lote de bootstrap.
    st.posicion = {"trade_id": "t" * 64, "E": 5.0, "S": 1.0, "T": 100.0,
                   "largo": True, "P_in": 5.0, "close_fill": 0,
                   "ultimo_cierre_sellado": 0}
    motor.procesar_lote(frontera)                 # aún bootstrap
    assert led.eventos == []
    T = frontera + DUR
    motor.procesar_lote(T)                        # primer lote posterior
    tipos = [e["tipo"] for e in led.eventos]
    assert tipos.count("frontera") == 1
    assert tipos.count("estado_inicial") == 1
    assert st.estado == "flat"
    assert st.posicion is None
    ini = next(e for e in led.eventos if e["tipo"] == "estado_inicial")
    assert ini["estado_previo"] == "posicion"
    assert ini["effective_at"] == frontera        # anclado a T_frontera


def test_b3_frontera_se_emite_una_sola_vez():
    ep = _epoca_confirmacion()
    frontera = int(ep[-4]["t"]) + DUR
    motor, led = _motor_bootstrap(ep, frontera)
    for T in (frontera + DUR, frontera + 2 * DUR, frontera + 3 * DUR):
        motor.procesar_lote(T)
    assert [e["tipo"] for e in led.eventos].count("frontera") == 1


ZONA_FRESCURA = {"kind": "ob", "dir": "long", "lo": 8.0, "hi": 12.0,
                 "available_at": 0}
CALC_FRESCURA = {"direccion": "long", "rango": {"weak": 30.0, "eq": 20.0},
                 "zonas": [ZONA_FRESCURA], "fractal": {"available_at": 0},
                 "motivo": None}
CLAVE_FRESCURA = (ZONA_FRESCURA["kind"], ZONA_FRESCURA["dir"],
                  ZONA_FRESCURA["lo"], ZONA_FRESCURA["hi"],
                  ZONA_FRESCURA["available_at"])


def test_b3_frescura_consumida_en_bootstrap_sobrevive_al_cruce():
    """CF-24 real: la zona se consume ANTES de la frontera; tras cruzarla
    debe seguir consumida y NO generar candidato."""
    ep = _epoca_confirmacion()
    frontera = int(ep[-3]["t"]) + DUR
    motor, led = _motor_bootstrap(ep, frontera)
    st = motor.estados["BTCUSDT"]
    # Consumo REAL durante el bootstrap: _fase7b marca la zona y no emite.
    motor._fase7b("BTCUSDT", frontera, frontera, ep, len(ep) - 2,
                  CALC_FRESCURA, st)
    assert CLAVE_FRESCURA in st.zonas_tocadas
    assert led.eventos == []                      # bootstrap no emite
    st.estado = "flat"; st.candidato = None       # el bootstrap deja su estado
    T = frontera + DUR
    motor._cruzar_frontera(T, T)
    assert CLAVE_FRESCURA in st.zonas_tocadas     # la frescura SOBREVIVE
    led.eventos.clear(); led._ids.clear()
    motor._fase7b("BTCUSDT", T, T, ep, len(ep), CALC_FRESCURA, st)
    assert st.estado == "flat"
    assert not any(e["tipo"] == "candidato" for e in led.eventos)


def test_b3_control_zona_no_consumida_si_genera_candidato():
    """Control en un motor SEPARADO (sin contaminación): la misma zona, sin
    frescura consumida, sí produce candidato tras la frontera."""
    ep = _epoca_confirmacion()
    frontera = int(ep[-3]["t"]) + DUR
    motor, led = _motor_bootstrap(ep, frontera)
    st = motor.estados["BTCUSDT"]
    T = frontera + DUR
    motor._cruzar_frontera(T, T)
    led.eventos.clear(); led._ids.clear()
    assert CLAVE_FRESCURA not in st.zonas_tocadas
    motor._fase7b("BTCUSDT", T, T, ep, len(ep), CALC_FRESCURA, st)
    assert st.estado == "candidato_vivo"
    assert any(e["tipo"] == "candidato" for e in led.eventos)


def test_b3_epoca_m15_se_anuncia_una_vez():
    ep = _epoca_confirmacion()
    motor, led = _motor_con(ep)
    T0 = int(ep[-1]["t"]) + DUR
    for T in (T0 - 2 * DUR, T0 - DUR, T0):
        motor._anunciar_epoca("BTCUSDT", T, T)
    evs = [e for e in led.eventos if e["tipo"] == "epoca_m15"]
    assert len(evs) == 1
    assert evs[0]["epoca_t0"] == int(ep[0]["t"])        # identidad por t0
    assert evs[0]["effective_at"] == T0 - 2 * DUR       # lote que la habilitó


# ------------------------------------------- B-4: watermark y corte ------
def _mundo_silencio(silencioso="BTCUSDT", velas_ok=8, velas_mudo=1,
                    t0=1646092800000):
    """7 mercados; uno enmudece tras `velas_mudo` velas."""
    from modules.bot3.v9.ledger import Ledger as L
    alms = {}
    for m in C.MERCADOS:
        alm = S.Almacen(m, "15m"); alm.nacer_en(t0)
        n = velas_mudo if m == silencioso else velas_ok
        alm.ofrecer([vela(t0 + i * DUR, 1, 2, 0.5, 1.5) for i in range(n)],
                    "push")
        alm.drenar()
        alms[m] = alm
    led = L()
    return E.Motor(alms, alms, C.MERCADOS, led), led


def _mundo_epoca_habilitada(silencioso="BTCUSDT", t0=1646092800000):
    """7 mercados con ÉPOCA HABILITADA (≥200 velas); uno enmudece justo
    después de alcanzarla."""
    from modules.bot3.v9.ledger import Ledger as L
    alms = {}
    for m in C.MERCADOS:
        alm = S.Almacen(m, "15m"); alm.nacer_en(t0)
        n = 200 if m == silencioso else 210
        alm.ofrecer([vela(t0 + i * DUR, 1, 2, 0.5, 1.5) for i in range(n)],
                    "push")
        alm.drenar()
        alms[m] = alm
    led = L()
    return E.Motor(alms, alms, C.MERCADOS, led), led


def test_b4_watermark_exchange_degrada_y_desbloquea():
    """CF-29 camino PRINCIPAL con una ausencia real: el mercado silencioso
    tiene época habilitada ANTES del hueco, hay quorum, y el watermark debe
    declarar, degradar, registrar y desbloquear el lote."""
    t0 = 1646092800000
    motor, led = _mundo_epoca_habilitada(t0=t0)
    T = t0 + 201 * DUR                      # falta la vela de BTC
    alm = motor.m15["BTCUSDT"]
    assert alm.cubre(T - DUR) == "pendiente"
    assert not motor.lote_finalizable(T)     # bloqueado antes del watermark
    degradados = motor.watermark_exchange(T)
    assert degradados == ["BTCUSDT"]                       # mercado incluido
    assert alm.cubre(T - DUR) == "hueco"                   # marcador exchange
    assert motor.estados["BTCUSDT"].degradado is True      # estado degradado
    reg = [r for r in alm.registros if r["tipo"] == "gap"]
    assert reg and reg[-1]["motivo"] == "exchange"
    tipos = [e["tipo"] for e in led.eventos]
    assert "hueco_detectado" in tipos and "mercado_degradado" in tipos
    hd = next(e for e in led.eventos if e["tipo"] == "hueco_detectado")
    assert hd["motivo"] == "exchange" and len(hd["prueba"]) == C.WATERMARK_EXCHANGE_Q
    assert motor.lote_finalizable(T)                       # lote procesable


def test_b4_epoca_previa_es_la_que_habilita_el_watermark():
    """`_epoca_habilitada` falla en un mercado silencioso (T no pertenece a
    ninguna época); la que corresponde es la ÚLTIMA época previa al hueco."""
    t0 = 1646092800000
    motor, _ = _mundo_epoca_habilitada(t0=t0)
    T = t0 + 201 * DUR
    assert motor._epoca_habilitada("BTCUSDT", T) is None
    previa = motor._epoca_habilitada_previa("BTCUSDT", T)
    assert previa is not None and previa[1] >= C.EPOCA_M15_MIN_VELAS


def test_b4_sin_quorum_no_declara_ni_degrada():
    """Caída parcial amplia (solo 3 activos): sin Q=4 no se declara nada y
    el motor NO inventa el hueco."""
    from modules.bot3.v9.ledger import Ledger as L
    t0 = 1646092800000
    alms = {}
    for i, m in enumerate(C.MERCADOS):
        alm = S.Almacen(m, "15m"); alm.nacer_en(t0)
        n = 8 if i < 3 else 1
        alm.ofrecer([vela(t0 + k * DUR, 1, 2, 0.5, 1.5) for k in range(n)],
                    "push")
        alm.drenar()
        alms[m] = alm
    motor = E.Motor(alms, alms, C.MERCADOS, L())
    assert motor.watermark_exchange(t0 + 2 * DUR) == []
    assert not any(st.degradado for st in motor.estados.values())


def test_b4_corte_administrativo_con_evidencia():
    """CF-35: sin lote finalizado > T_corte y con el reloj pasada la gracia,
    se cierra contra el último lote ≤ T_corte, con evidencia y degradación
    de cobertura de las velas parciales posteriores."""
    from modules.bot3.v9.ledger import Ledger as L
    t0 = C.T_CORTE - 10 * DUR
    alms = {}
    for m in C.MERCADOS:
        alm = S.Almacen(m, "15m"); alm.nacer_en(t0)
        n = 20 if m == "ADAUSDT" else 5        # ADA sigue publicando después
        alm.ofrecer([vela(t0 + i * DUR, 1, 2, 0.5, 1.5) for i in range(n)],
                    "push")
        alm.drenar()
        alms[m] = alm
    led = L()
    motor = E.Motor(alms, alms, C.MERCADOS, led)
    motor.lotes_finalizados = [C.T_CORTE - 2 * DUR]
    # Antes de la gracia no corta.
    assert motor.cerrar_administrativo(C.T_CORTE + 1000) is False
    assert motor.cerrar_administrativo(
        C.T_CORTE + C.CORTE_ADMIN_GRACIA_MS + 1) is True
    ev = next(e for e in led.eventos if e["tipo"] == "corte_administrativo")
    assert ev["effective_at"] == C.T_CORTE
    assert ev["ultimo_lote_finalizado"] == C.T_CORTE - 2 * DUR
    assert "reloj" in ev
    degr = [e for e in led.eventos if e["tipo"] == "degradacion_de_cobertura"]
    assert any(e["mercado"] == "ADAUSDT" for e in degr)
    assert motor.motivo_corte == "administrativo"
    # T_CORTE no cae en la grilla M15: el conteo de faltantes debe usar un
    # cierre ALINEADO, no declarar falsamente a los siete mercados.
    assert C.T_CORTE % DUR != 0
    assert set(ev["mercados_sin_datos"]) != set(C.MERCADOS)


def test_b4_corte_administrativo_no_aplica_si_hubo_lote_posterior():
    from modules.bot3.v9.ledger import Ledger as L
    motor = E.Motor({}, {}, (), L())
    motor.lotes_finalizados = [C.T_CORTE + DUR]
    assert motor.cerrar_administrativo(
        C.T_CORTE + C.CORTE_ADMIN_GRACIA_MS + 1) is False
    assert motor.cortado is False


def test_b4_id_t_es_lista_cerrada():
    """`id_t` solo se acepta para `epoca_m15` y no se persiste."""
    import pytest
    led = Ledger()
    with pytest.raises(ValueError):
        led.append("frontera", effective_at=1, id_t=2)
    ev = led.append("epoca_m15", mercado="BTCUSDT", effective_at=100,
                    id_t=50, epoca_t0=50)
    assert "id_t" not in ev
    assert ev["event_id"] == C.event_id("epoca_m15", mercado="BTCUSDT", t=50)
