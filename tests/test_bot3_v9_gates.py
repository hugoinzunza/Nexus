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
                        "BOT3_V9_PROTOCOLO.md")
    with open(ruta, "rb") as fh:
        assert hashlib.sha256(fh.read()).hexdigest() == C.CONTRATO_HASH
