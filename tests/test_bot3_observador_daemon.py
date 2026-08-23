"""Observador Bot3.v13 — gates del ciclo contra el Motor y el Ledger REALES.

La versión anterior de estos gates usaba un motor sustituto, y por eso no
detectaba que el daemon llamaba a un método inexistente: el primer ciclo real
habría muerto con `AttributeError`. Acá no hay dobles del motor ni del libro.

Las cuatro propiedades exigidas:

- ningún ciclo ingiere sin reloj;
- `pending`/`deferred` impiden el corte científico;
- ningún terminal parcial se publica;
- la barrera se RETIENE, no se readquiere.
"""
import json
import os

import pytest

from modules.bot3.observador import contrato as C
from modules.bot3.observador import daemon as D
from modules.bot3.observador import estado as E
from modules.bot3.observador import silencio as SIL
from modules.bot3.v9 import store as S
from modules.bot3.v9.contract import (CORTE_ADMIN_GRACIA_MS, CORTE_N_CIERRES,
                                      GENESIS_H4, T_CORTE, TF_MS)
from modules.bot3.v9.engine import Motor
from modules.bot3.v9.ledger import Ledger

DUR = TF_MS["15m"]
DUR4 = TF_MS["4h"]
T0 = GENESIS_H4 + 4000 * DUR4                  # alineado a las dos grillas
MERCADOS = ("BTCUSDT", "ETHUSDT")
IDENT = {"cohorte": "ensayo", "contrato": "x" * 64, "commit": "y" * 40}


def vela(t, p=100.0):
    return {"t": t, "o": p, "h": p + 1, "l": p - 1, "c": p + 0.5, "v": 1.0}


def mundo(tmp_path, n15=210, n4=None, mercados=MERCADOS):
    """Motor, almacenes y libro REALES, respaldados por archivos."""
    n4 = n4 if n4 is not None else (n15 * DUR) // DUR4 + 2
    m15, h4 = {}, {}
    for m in mercados:
        a = S.Almacen(m, "15m", ruta=str(tmp_path / f"{m}_15m.jsonl"))
        a.nacer_en(T0)
        a.ofrecer([vela(T0 + i * DUR, 100 + i * 0.1) for i in range(n15)],
                  "push")
        a.drenar()
        m15[m] = a
        b = S.Almacen(m, "4h", ruta=str(tmp_path / f"{m}_4h.jsonl"))
        b.nacer_en(T0)
        b.ofrecer([vela(T0 + i * DUR4, 100 + i) for i in range(n4)], "push")
        b.drenar()
        h4[m] = b
    libro = Ledger(str(tmp_path / "libro.jsonl"), commit="ensayo")
    motor = Motor(m15, h4, mercados, libro, bootstrap_hasta=1)
    return motor, m15, h4, libro


def ahora_de(m15, h4):
    """Reloj contemporáneo: el cierre de la última vela M15.

    H4 se construye un poco más largo a propósito, así que su grilla ya está
    resuelta hasta acá. Tomar el máximo dejaría M15 stale y el ciclo nunca
    procesaría — el lag mediría dos épocas distintas."""
    return min(a.ultimo_t + DUR for a in m15.values())


def fetch_reloj(reloj, paginas=None):
    def fetch(url, params):
        if url == C.ENDPOINT_TIME:
            if isinstance(reloj, Exception):
                raise reloj
            return reloj if not isinstance(reloj, int) \
                else {"serverTime": reloj}
        return (paginas or {}).get((params["symbol"], params["interval"]), [])
    return fetch


def verif(tmp_path, nombre="v.json"):
    return E.Verificacion(str(tmp_path / nombre))


def sidecar_ok(d, instante=1):
    """§13.4.2: reanudar EXIGE un sidecar legible, para cualquier ganador. Sin
    él no se sabe si hay una comparación `pending` que deba retener."""
    v = E.Verificacion(os.path.join(d, C.ARCHIVO_VERIFICACION))
    v.conforme(instante, "d", "f")
    return v


def cerrar_y_publicar(d, motor, m15, h4, libro, v, ahora, barrera=None):
    """Lo que hace el ciclo: anota la causa del corte y publica una vez."""
    barrera = barrera or D.BarreraCiclo()
    causa = D.cerrar_si_corresponde(barrera, d, IDENT, motor, m15, h4, libro,
                                    v, ahora)
    if causa is None or causa["estado"] == "espera":
        return causa
    D.registrar_causa(barrera, d, causa["motivo"], IDENT, causa["evidencia"],
                      ahora, m15, h4, libro)
    return D.publicar_pendiente(barrera, d, ahora, motor, m15, h4, libro, v,
                                IDENT)


# ==================== 1. ningún ciclo ingiere sin reloj ====================
def test_ningun_ciclo_ingiere_sin_reloj(tmp_path):
    motor, m15, h4, libro = mundo(tmp_path)
    v = verif(tmp_path)
    heads = {m: a.head for m, a in m15.items()}
    firma = libro.firma()

    for reloj in (None, {}, {"serverTime": "x"}, [], RuntimeError("timeout")):
        def fetch(url, params, _r=reloj):
            if url == C.ENDPOINT_TIME:
                if isinstance(_r, Exception):
                    raise _r
                return _r
            raise AssertionError("no se puede pedir velas sin reloj")

        parte = D.ciclo(fetch, D.BarreraCiclo(), motor, m15, h4, libro, v,
                        lambda: T0)
        assert parte["ingirio"] is False
        assert "sin reloj" in parte["motivo"]
    assert {m: a.head for m, a in m15.items()} == heads
    assert libro.firma() == firma                  # el libro no se movió


def test_un_ciclo_usa_UN_solo_serverTime_end_to_end(tmp_path):
    """El reloj se muestrea una vez y ANTES de la barrera."""
    motor, m15, h4, libro = mundo(tmp_path)
    v = verif(tmp_path)
    ahora = ahora_de(m15, h4)
    pedidos, relojes = [], iter([ahora, ahora + 10 ** 6, ahora + 2 * 10 ** 6])

    def fetch(url, params):
        pedidos.append(url)
        if url == C.ENDPOINT_TIME:
            return {"serverTime": next(relojes)}
        return []

    parte = D.ciclo(fetch, D.BarreraCiclo(), motor, m15, h4, libro, v,
                    lambda: 424242)
    assert pedidos.count(C.ENDPOINT_TIME) == 1
    assert parte["eligibility_time"] == ahora
    # `processed_at` sale del reloj LOCAL (CF-34), no del de Binance
    procesados = [e for e in libro.eventos if "processed_at" in e]
    assert procesados and all(e["processed_at"] == 424242 for e in procesados)


# ============ 2. el ciclo corre contra el motor REAL de punta a punta ======
def test_el_ciclo_procesa_lotes_con_el_motor_real(tmp_path):
    """El gate que faltaba: sin motor sustituto, un método inexistente mata el
    ciclo. Acá el `Motor` de `engine.py` produce eventos de verdad."""
    motor, m15, h4, libro = mundo(tmp_path)
    v = verif(tmp_path)
    ahora = ahora_de(m15, h4)
    parte = D.ciclo(fetch_reloj(ahora), D.BarreraCiclo(), motor, m15, h4,
                    libro, v, lambda: ahora)
    assert parte["ingirio"] is True
    assert parte["decision"]["procesar"] is True
    assert len(parte["procesados"]) > 100          # lotes reales procesados
    assert parte["ultimo_T"] == parte["procesados"][-1]
    tipos = {e["tipo"] for e in libro.eventos}
    assert "lote_finalizado" in tipos              # el motor emitió de verdad
    assert motor.lotes_finalizados


def test_el_ciclo_sigue_la_secuencia_canonica_por_lote(tmp_path):
    """`recuperar_exchange → lote_finalizable → watermark_exchange →
    reevaluar → procesar_lote`, el mismo orden de `runner.correr`."""
    motor, m15, h4, libro = mundo(tmp_path, n15=60)
    v = verif(tmp_path)
    orden = []
    nombres = ("recuperar_exchange", "lote_finalizable", "watermark_exchange",
               "procesar_lote")
    originales = {n: getattr(Motor, n) for n in nombres}
    for nombre in nombres:
        def envuelto(self, T, _n=nombre, _o=originales[nombre]):
            orden.append(_n)
            return _o(self, T)

        setattr(Motor, nombre, envuelto)
    try:
        ahora = ahora_de(m15, h4)
        D.ciclo(fetch_reloj(ahora), D.BarreraCiclo(), motor, m15, h4, libro,
                v, lambda: ahora)
    finally:
        for nombre, real in originales.items():
            setattr(Motor, nombre, real)
    # primer lote: recuperar antes que evaluar, y procesar al final
    assert orden[0] == "recuperar_exchange"
    assert orden[1] == "lote_finalizable"
    assert "procesar_lote" in orden
    assert orden.index("recuperar_exchange") < orden.index("procesar_lote")


def test_los_huecos_locales_sellados_llegan_al_libro(tmp_path):
    """El daemon los emite por la vía canónica, con heads y provenance."""
    motor, m15, h4, libro = mundo(tmp_path, n15=60)
    alm = m15["BTCUSDT"]
    # hueco artificial: se ofrece salteado y el watermark local lo sella
    alm.ofrecer([vela(alm.ultimo_t + (2 + i) * DUR) for i in range(4)], "push")
    alm.drenar()
    assert alm.declarar_hueco_local() is not None
    ahora = ahora_de(m15, h4)
    D.ciclo(fetch_reloj(ahora), D.BarreraCiclo(), motor, m15, h4, libro, v_
            := verif(tmp_path), lambda: ahora)
    huecos = [e for e in libro.eventos if e["tipo"] == "hueco_detectado"]
    assert huecos and huecos[0]["motivo"] == "local"
    for campo in ("processed_at", "input_head_asof_T", "input_commit_asof_T",
                  "provenance_head_at_finality"):
        assert campo in huecos[0], campo


# ================== 3. zona de corte y verificación =======================
def test_dentro_de_la_zona_no_se_procesa_sin_verificacion_ok(tmp_path):
    motor, m15, h4, libro = mundo(tmp_path, n15=60)
    motor.cierres = [{"t": i} for i in range(CORTE_N_CIERRES - 1)]
    motor.estados["BTCUSDT"].posicion = {"P_in": 1}
    assert D.en_zona_de_corte(motor, T0) is True
    v = verif(tmp_path)
    for preparar in (lambda: v.pendiente(1, "d", "f"),
                     lambda: v.diferir(1, {"BTCUSDT_15m": 2}),
                     lambda: v.divergente(1, {}, {})):
        preparar()
        assert D.puede_procesar_lote(motor, T0, v)["procesar"] is False
    v.conforme(10, "d", "f")
    v.diferir(20, {"BTCUSDT_4h": 1})               # `ok` ANTERIOR no habilita
    assert D.puede_procesar_lote(motor, T0, v)["procesar"] is False
    v.conforme(30, "d", "f")
    assert D.puede_procesar_lote(motor, T0, v)["procesar"] is True


def test_el_ciclo_real_no_procesa_ningun_lote_en_la_zona_sin_ok(tmp_path):
    """De punta a punta con el motor real: el libro no recibe un solo evento
    de lote mientras la verificación no sea `ok`."""
    motor, m15, h4, libro = mundo(tmp_path, n15=60)
    motor.cierres = [{"t": i} for i in range(CORTE_N_CIERRES - 1)]
    motor.estados["BTCUSDT"].posicion = {"P_in": 1}
    v = verif(tmp_path)
    v.pendiente(1, "d", "f")
    ahora = ahora_de(m15, h4)
    parte = D.ciclo(fetch_reloj(ahora), D.BarreraCiclo(), motor, m15, h4,
                    libro, v, lambda: ahora)
    assert parte["procesados"] == []
    assert parte["bloqueado_por"]["zona_de_corte"] is True
    assert not [e for e in libro.eventos if e["tipo"] == "lote_finalizado"]


def test_la_zona_de_corte_tambien_la_abre_el_tiempo(tmp_path):
    motor, *_ = mundo(tmp_path, n15=30)
    motor.cierres = []
    motor.estados["BTCUSDT"].posicion = None
    assert D.en_zona_de_corte(motor, T_CORTE - CORTE_ADMIN_GRACIA_MS - 1) is False
    assert D.en_zona_de_corte(motor, T_CORTE - CORTE_ADMIN_GRACIA_MS) is True


# =================== 4. verificación vivo ↔ frío REAL =====================
def test_la_captura_exige_la_barrera_RETENIDA(tmp_path):
    motor, m15, h4, libro = mundo(tmp_path, n15=30)
    v = verif(tmp_path)
    barrera = D.BarreraCiclo()
    with pytest.raises(RuntimeError, match="RETENIDA"):
        D.capturar(barrera, motor, m15, h4, libro, None,
                   str(tmp_path / "scratch"), T0, v)
    with barrera:
        assert D.capturar(barrera, motor, m15, h4, libro, None,
                          str(tmp_path / "scratch"), T0, v)


def test_una_barrera_con_buffers_llenos_no_se_certifica(tmp_path):
    motor, m15, h4, libro = mundo(tmp_path, n15=30)
    m15["BTCUSDT"].ofrecer([vela(m15["BTCUSDT"].ultimo_t + 5 * DUR)], "push")
    assert D.buffers_no_vacios(m15, h4) == {"BTCUSDT_15m": 1}
    v = verif(tmp_path)
    barrera = D.BarreraCiclo()
    with barrera:
        assert D.capturar(barrera, motor, m15, h4, libro, None,
                          str(tmp_path / "scratch"), T0, v) is None
    assert v.estado == C.VERIF_DIFERIDA and v.habilita_cierre() is False
    assert not os.path.exists(str(tmp_path / "scratch"))


def test_vivo_contra_frio_reconstruye_de_verdad_y_coincide(tmp_path):
    """El clon frío recarga los almacenes con `Almacen.cargar` —que revalida
    la cadena entera—, relee el libro del archivo y rehace la secuencia
    canónica. No recibe el digest ya calculado."""
    motor, m15, h4, libro = mundo(tmp_path, n15=210)
    v = verif(tmp_path)
    ahora = ahora_de(m15, h4)
    D.ciclo(fetch_reloj(ahora), D.BarreraCiclo(), motor, m15, h4, libro, v,
            lambda: ahora)
    barrera = D.BarreraCiclo()
    with barrera:
        captura = D.capturar(barrera, motor, m15, h4, libro, None,
                             str(tmp_path / "scratch"), ahora, v)
    assert v.estado == C.VERIF_PENDIENTE and v.habilita_cierre() is False
    resultado = D.verificar_en_frio(captura, v, ahora + 1, commit="ensayo")
    assert resultado["igual"] is True, (resultado, captura)
    assert v.estado == C.VERIF_OK and v.habilita_cierre() is True


def test_una_divergencia_real_deja_la_cohorte_inhabilitada(tmp_path):
    """Se altera el estado VIVO tras la captura: el clon frío ya no coincide."""
    motor, m15, h4, libro = mundo(tmp_path, n15=120)
    v = verif(tmp_path)
    ahora = ahora_de(m15, h4)
    D.ciclo(fetch_reloj(ahora), D.BarreraCiclo(), motor, m15, h4, libro, v,
            lambda: ahora)
    barrera = D.BarreraCiclo()
    with barrera:
        captura = D.capturar(barrera, motor, m15, h4, libro, None,
                             str(tmp_path / "scratch"), ahora, v)
    captura["digest"] = "0" * 64                   # el vivo dijo otra cosa
    resultado = D.verificar_en_frio(captura, v, ahora + 1, commit="ensayo")
    assert resultado["igual"] is False
    assert v.estado == C.VERIF_DIVERGENTE
    assert v.habilita_cierre() is False


def test_la_captura_copia_el_sidecar_de_silencio(tmp_path):
    motor, m15, h4, libro = mundo(tmp_path, n15=30)
    s = SIL.Silencio(IDENT["cohorte"], IDENT["contrato"], IDENT["commit"])
    s.abrir_corrida()
    falt = h4["BTCUSDT"].ultimo_t + DUR4
    s.observar("BTCUSDT", "4h", falt, h4["BTCUSDT"].ultimo_t, T0)
    v = verif(tmp_path)
    barrera = D.BarreraCiclo()
    with barrera:
        captura = D.capturar(barrera, motor, m15, h4, libro, s,
                             str(tmp_path / "scratch"), T0, v)
    assert os.path.exists(captura["silencio"])
    _, _, _, _, doc = D.reconstruir_en_frio(captura, commit="ensayo")
    assert doc is not None and doc["entradas"]


# ======================= 5. silencio conectado ============================
def test_el_silencio_se_persiste_en_cada_ciclo(tmp_path):
    """Sin persistir, un reinicio pierde las observaciones y las 72 h nunca
    producirían un terminal."""
    motor, m15, h4, libro = mundo(tmp_path, n15=30)
    d = str(tmp_path / "estado")
    os.makedirs(d)
    s = SIL.Silencio(IDENT["cohorte"], IDENT["contrato"], IDENT["commit"])
    s.abrir_corrida()
    v = verif(tmp_path)
    ahora = ahora_de(m15, h4)
    D.ciclo(fetch_reloj(ahora), D.BarreraCiclo(), motor, m15, h4, libro, v,
            lambda: ahora, silencio=s, estado_dir=d, identidad=IDENT)
    ruta = os.path.join(d, C.ARCHIVO_SILENCIO)
    assert os.path.exists(ruta)
    SIL.Silencio.cargar(ruta, IDENT["cohorte"], IDENT["contrato"],
                        IDENT["commit"])          # rehidrata sin quejarse


def test_solo_la_llegada_REAL_de_la_vela_resuelve_el_silencio(tmp_path):
    """Resolver ante cualquier observación no probatoria dejaba que una
    regresión de `serverTime` —que vuelve la vela no exigible— marcara
    resuelto un silencio sin que la vela hubiera llegado."""
    motor, m15, h4, libro = mundo(tmp_path, n15=30)
    s = SIL.Silencio(IDENT["cohorte"], IDENT["contrato"], IDENT["commit"])
    s.abrir_corrida()
    alm = h4["BTCUSDT"]
    falt = alm.ultimo_t + DUR4
    k = SIL.clave("BTCUSDT", "4h", falt)
    s.observar("BTCUSDT", "4h", falt, alm.ultimo_t, T0)

    # la vela NO llegó y el reloj retrocede: la ausencia deja de ser exigible
    partes = [{"mercado": "BTCUSDT", "tf": "4h", "esperada": falt,
               "ultimo_t": alm.ultimo_t, "observacion_probatoria": False,
               "trajo_esperada": False}]
    D._actualizar_silencio(s, partes, T0, h4)
    assert s.entradas[k]["estado"] == "activo"     # NO se resolvió

    # ahora sí llega: gobierna el HECHO de que la respuesta la trajo
    partes[0]["trajo_esperada"] = True
    D._actualizar_silencio(s, partes, T0, h4)
    assert s.entradas[k]["estado"] == "resuelto"


def test_un_backfill_posterior_al_sellado_igual_resuelve(tmp_path):
    """La vela llega DESPUÉS de que el hueco se selló: queda como
    `vela_no_incorporada` y `cubre()` nunca diría «vela», así que gobernar por
    el almacén dejaba el silencio activo para siempre."""
    motor, m15, h4, libro = mundo(tmp_path, n15=30)
    s = SIL.Silencio(IDENT["cohorte"], IDENT["contrato"], IDENT["commit"])
    s.abrir_corrida()
    alm = h4["BTCUSDT"]
    falt = alm.ultimo_t + DUR4
    k = SIL.clave("BTCUSDT", "4h", falt)
    s.observar("BTCUSDT", "4h", falt, alm.ultimo_t, T0)
    # se sella el hueco con el watermark local
    alm.ofrecer([vela(falt + (i + 1) * DUR4) for i in range(3)], "push")
    alm.drenar()
    assert alm.declarar_hueco_local() is not None
    assert alm.cubre(falt) == "hueco"               # NUNCA será "vela"
    partes = [{"mercado": "BTCUSDT", "tf": "4h", "esperada": falt,
               "ultimo_t": alm.ultimo_t, "observacion_probatoria": False,
               "trajo_esperada": True}]
    D._actualizar_silencio(s, partes, T0, h4)
    assert s.entradas[k]["estado"] == "resuelto"


def test_el_silencio_ganador_dispara_el_terminal(tmp_path):
    """Las 72 h acumuladas terminan en `BLOCKED_INTEGRITY`, no en espera."""
    motor, m15, h4, libro = mundo(tmp_path, n15=30)
    d = str(tmp_path / "estado")
    os.makedirs(d)
    s = SIL.Silencio(IDENT["cohorte"], IDENT["contrato"], IDENT["commit"])
    s.abrir_corrida()
    alm = h4["BTCUSDT"]
    falt = alm.ultimo_t + DUR4
    base = ahora_de(m15, h4)
    for i in range(C.SILENCIO_MAX_H4_MS // C.CADENCIA_MS + 2):
        s.observar("BTCUSDT", "4h", falt, alm.ultimo_t,
                   base + i * C.CADENCIA_MS)
    assert s.ganadora() is not None
    barrera = D.BarreraCiclo()
    v = verif(tmp_path)
    parte = D.ciclo(fetch_reloj(base), barrera, motor, m15, h4, libro, v,
                    lambda: base, silencio=s, estado_dir=d, identidad=IDENT)
    assert parte["terminal"]["estado"] == C.BLOQUEADO
    cuerpo = json.load(open(os.path.join(d, C.ARCHIVO_BLOQUEADO),
                            encoding="utf-8"))
    assert cuerpo["motivo"] == C.MOTIVO_SILENCIO
    assert cuerpo["evidencia"]["mercado"] == "BTCUSDT"
    assert barrera.terminal                        # no se abren ciclos nuevos


# ===================== 6. terminales y recuperación =======================
def test_publicado_el_terminal_no_se_abre_ningun_ciclo(tmp_path):
    motor, m15, h4, libro = mundo(tmp_path, n15=30)
    d = str(tmp_path / "estado")
    os.makedirs(d)
    barrera = D.BarreraCiclo()
    v = verif(tmp_path)
    D.transicion_terminal(barrera, d, C.MOTIVO_DIVERGENCIA, IDENT, {}, T0,
                          motor, m15, h4, libro)
    assert barrera.terminal == C.MOTIVO_DIVERGENCIA
    firma = libro.firma()
    parte = D.ciclo(fetch_reloj(ahora_de(m15, h4)), barrera, motor, m15, h4,
                    libro, v, lambda: T0)
    assert parte["ingirio"] is False
    assert "terminal" in parte["motivo"]
    assert libro.firma() == firma


def test_blocked_integrity_no_ejecuta_el_cierre_cientifico(tmp_path):
    motor, m15, h4, libro = mundo(tmp_path, n15=30)
    d = str(tmp_path / "estado")
    os.makedirs(d)
    firma = libro.firma()
    D.transicion_terminal(D.BarreraCiclo(), d, C.MOTIVO_DIVERGENCIA, IDENT,
                          {}, T0, motor, m15, h4, libro)
    assert motor.cortado is False
    assert libro.firma() == firma                  # el libro no se tocó
    assert not [e for e in libro.eventos
                if e["tipo"] in ("abierta_al_corte", "orden_al_corte")]


def test_una_caida_a_mitad_se_reanuda_y_no_ingiere(tmp_path):
    """`terminal.request` sin terminal: el arranque siguiente valida identidad
    y REANUDA la transición desde la barrera."""
    motor, m15, h4, libro = mundo(tmp_path, n15=30)
    d = str(tmp_path / "estado")
    os.makedirs(d)
    sidecar_ok(d)
    E.solicitar_terminal(os.path.join(d, C.ARCHIVO_SOLICITUD_TERMINAL),
                         C.MOTIVO_SILENCIO, IDENT, {"h": 1}, 5,
                         D.estado_esperado(d, m15, h4, libro))
    barrera = D.BarreraCiclo()
    hecho = D.reanudar(barrera, d, IDENT, motor, m15, h4, libro, T0)
    assert hecho["reanudado"] is True
    assert hecho["estado"] == C.BLOQUEADO
    assert barrera.terminal
    assert not os.path.exists(
        os.path.join(d, C.ARCHIVO_SOLICITUD_TERMINAL))
    assert D.reanudar(barrera, d, IDENT, motor, m15, h4, libro,
                      T0)["estado"] == C.BLOQUEADO


def test_un_request_de_otra_cohorte_falla_cerrado(tmp_path):
    motor, m15, h4, libro = mundo(tmp_path, n15=30)
    d = str(tmp_path / "estado")
    os.makedirs(d)
    ajeno = {**IDENT, "cohorte": "otra"}
    E.solicitar_terminal(os.path.join(d, C.ARCHIVO_SOLICITUD_TERMINAL),
                         C.MOTIVO_SILENCIO, ajeno, {}, 5, {})
    with pytest.raises(ValueError, match="otra cohorte"):
        D.reanudar(D.BarreraCiclo(), d, IDENT, motor, m15, h4, libro, T0)


def test_la_solicitud_se_escribe_DENTRO_de_la_barrera(tmp_path):
    """Si no, dos anexiones concurrentes no estarían serializadas y un ciclo
    en espera podría colarse entre la solicitud y la publicación."""
    motor, m15, h4, libro = mundo(tmp_path, n15=30)
    d = str(tmp_path / "estado")
    os.makedirs(d)
    barrera = D.BarreraCiclo()
    vista = []
    real = E.solicitar_terminal

    def espia(*a, **k):
        vista.append(barrera.retenida)
        return real(*a, **k)

    D.E.solicitar_terminal = espia
    try:
        D.transicion_terminal(barrera, d, C.MOTIVO_SILENCIO, IDENT, {}, T0,
                              motor, m15, h4, libro)
    finally:
        D.E.solicitar_terminal = real
    assert vista == [True]
    assert barrera.retenida is False


def test_la_reanudacion_exige_el_estado_QUE_EL_REQUEST_AUTORIZA(tmp_path):
    """Publicar sobre otros heads o firma sería cerrar la cohorte con un
    estado distinto del que se autorizó."""
    motor, m15, h4, libro = mundo(tmp_path, n15=30)
    d = str(tmp_path / "estado")
    os.makedirs(d)
    E.solicitar_terminal(os.path.join(d, C.ARCHIVO_SOLICITUD_TERMINAL),
                         C.MOTIVO_SILENCIO, IDENT, {}, 5,
                         D.estado_esperado(d, m15, h4, libro))
    # el almacén avanza DESPUÉS del request: ya no es el estado autorizado
    m15["BTCUSDT"].ofrecer([vela(m15["BTCUSDT"].ultimo_t + DUR)], "push")
    m15["BTCUSDT"].drenar()
    with pytest.raises(ValueError, match="autoriza otro estado"):
        D.reanudar(D.BarreraCiclo(), d, IDENT, motor, m15, h4, libro, T0)


def test_el_estado_esperado_incluye_los_sidecars(tmp_path):
    motor, m15, h4, libro = mundo(tmp_path, n15=30)
    d = str(tmp_path / "estado")
    os.makedirs(d)
    s = SIL.Silencio(IDENT["cohorte"], IDENT["contrato"], IDENT["commit"])
    s.abrir_corrida()
    s.observar("BTCUSDT", "4h", h4["BTCUSDT"].ultimo_t + DUR4,
               h4["BTCUSDT"].ultimo_t, T0)
    s.guardar(os.path.join(d, C.ARCHIVO_SILENCIO))
    antes = D.estado_esperado(d, m15, h4, libro)
    assert C.ARCHIVO_SILENCIO in antes["sidecars"]
    s.observar("BTCUSDT", "4h", h4["BTCUSDT"].ultimo_t + DUR4,
               h4["BTCUSDT"].ultimo_t, T0 + C.CADENCIA_MS)
    s.guardar(os.path.join(d, C.ARCHIVO_SILENCIO))
    assert D.estado_esperado(d, m15, h4, libro) != antes


def test_dos_causas_del_MISMO_ciclo_las_resuelve_la_precedencia(tmp_path):
    """La ruta REAL: el ciclo ANOTA las causas y publica una sola vez al
    final. Con una sola fase, dos causas quedaban serializadas por la barrera
    y la primera publicaba de inmediato — en operación ganaba siempre quien
    publicaba primero, no la precedencia."""
    for orden in (( C.MOTIVO_SILENCIO, C.MOTIVO_DIVERGENCIA),
                  (C.MOTIVO_DIVERGENCIA, C.MOTIVO_SILENCIO)):
        sub = tmp_path / f"ciclo_{orden[0]}"
        sub.mkdir()
        motor, m15, h4, libro = mundo(sub, n15=30)
        d = str(sub / "estado")
        os.makedirs(d)
        barrera = D.BarreraCiclo()
        for motivo in orden:                        # anotadas, sin publicar
            D.registrar_causa(barrera, d, motivo, IDENT,
                              {"de": motivo}, T0, m15, h4, libro)
        assert not os.path.exists(os.path.join(d, C.ARCHIVO_BLOQUEADO))
        hecho = D.publicar_pendiente(barrera, d, T0, motor, m15, h4, libro)
        assert hecho["cuerpo"]["motivo"] == C.MOTIVO_DIVERGENCIA, orden
        # y la EVIDENCIA es la del ganador, no la de la otra causa
        assert hecho["cuerpo"]["evidencia"] == {"de": C.MOTIVO_DIVERGENCIA}
        assert C.MOTIVO_SILENCIO in hecho["cuerpo"]["motivos_adicionales"]
        assert barrera.terminal == C.MOTIVO_DIVERGENCIA


def test_la_precedencia_se_resuelve_en_el_REQUEST_no_al_publicar(tmp_path):
    """Con dos motivos acumulados en un request PENDIENTE, gana la
    divergencia en los dos órdenes: la precedencia se resuelve mientras el
    request existe, antes de publicar."""
    for primero, segundo in ((C.MOTIVO_DIVERGENCIA, C.MOTIVO_SILENCIO),
                             (C.MOTIVO_SILENCIO, C.MOTIVO_DIVERGENCIA)):
        sub = tmp_path / f"req_{primero}"
        sub.mkdir()
        motor, m15, h4, libro = mundo(sub, n15=30)
        d = str(sub / "estado")
        os.makedirs(d)
        ruta = os.path.join(d, C.ARCHIVO_SOLICITUD_TERMINAL)
        E.solicitar_terminal(ruta, primero, IDENT, {}, T0,
                             D.estado_esperado(d, m15, h4, libro))
        E.solicitar_terminal(ruta, segundo, IDENT, {}, T0 + 1,
                             D.estado_esperado(d, m15, h4, libro))
        assert json.load(open(ruta, encoding="utf-8"))["motivo"] == \
            C.MOTIVO_DIVERGENCIA, (primero, segundo)
        # y la transición publica ESE motivo, no el que traiga la llamada
        hecho = D.transicion_terminal(D.BarreraCiclo(), d, primero, IDENT, {},
                                      T0 + 2, motor, m15, h4, libro)
        assert hecho["cuerpo"]["motivo"] == C.MOTIVO_DIVERGENCIA


def test_un_terminal_PUBLICADO_es_inmutable(tmp_path):
    """Permitir reemplazo era peor que un orden equivocado: con un
    `COMPLETED` por `muestra` —motivo científico, sin precedencia sobre la
    integridad— una
    divergencia posterior publicaba `blocked.json` SIN borrar
    `completed.json`, y el arranque siguiente encontraba los dos."""
    for estado, motivo in ((C.BLOQUEADO, C.MOTIVO_SILENCIO),
                           (C.COMPLETADO, "muestra")):
        sub = tmp_path / f"pub_{estado}"
        sub.mkdir()
        motor, m15, h4, libro = mundo(sub, n15=30)
        d = str(sub / "estado")
        os.makedirs(d)
        E.publicar_terminal(d, estado, {"cohorte": IDENT["cohorte"],
                                        "motivo": motivo})
        antes = os.listdir(d)
        barrera = D.BarreraCiclo()
        dos = D.transicion_terminal(barrera, d, C.MOTIVO_DIVERGENCIA, IDENT,
                                    {}, T0, motor, m15, h4, libro)
        assert dos.get("ya_existia") is True
        assert dos["cuerpo"]["motivo"] == motivo   # el publicado manda
        assert barrera.terminal == motivo
        # y NUNCA coexisten los dos archivos
        assert sorted(os.listdir(d)) == sorted(antes)
        assert not (os.path.exists(os.path.join(d, C.ARCHIVO_COMPLETADO))
                    and os.path.exists(os.path.join(d, C.ARCHIVO_BLOQUEADO)))
        E.leer_terminal(d)                         # no falla cerrado


def test_el_watermark_de_lotes_se_deriva_del_motor(tmp_path):
    """No se recibe de afuera: si el llamador lo omitiera o lo perdiera en un
    reinicio, el ciclo recorrería otra vez toda la historia sobre el mismo
    motor vivo."""
    motor, m15, h4, libro = mundo(tmp_path, n15=120)
    v = verif(tmp_path)
    ahora = ahora_de(m15, h4)
    primero = D.ciclo(fetch_reloj(ahora), D.BarreraCiclo(), motor, m15, h4,
                      libro, v, lambda: ahora)
    assert primero["procesados"]
    assert D.watermark_lotes(motor) == max(motor.lotes_finalizados)
    n_eventos = len(libro.eventos)
    # un segundo ciclo SIN datos nuevos no puede reprocesar nada
    segundo = D.ciclo(fetch_reloj(ahora), D.BarreraCiclo(), motor, m15, h4,
                      libro, v, lambda: ahora)
    assert segundo["procesados"] == []
    assert len(libro.eventos) == n_eventos


def test_el_corte_del_motor_publica_COMPLETED(tmp_path):
    """Sin esto, `motor.cortado` no producía ningún terminal y un `main`
    futuro habría tenido que inventar la orquestación."""
    motor, m15, h4, libro = mundo(tmp_path, n15=30)
    d = str(tmp_path / "estado")
    os.makedirs(d)
    v = verif(tmp_path)
    v.conforme(1, "d", "f")
    motor.cortado = True
    motor.motivo_corte = "muestra"
    hecho = cerrar_y_publicar(d, motor, m15, h4, libro, v, T0)
    assert hecho["estado"] == C.COMPLETADO
    cuerpo = json.load(open(os.path.join(d, C.ARCHIVO_COMPLETADO),
                            encoding="utf-8"))
    assert cuerpo["motivo"] == "muestra"
    assert cuerpo["heads"] and cuerpo["firma"] == libro.firma()


def test_COMPLETED_no_se_publica_sin_verificacion_ok(tmp_path):
    """El corte ya ocurrió y no se pierde: se espera al ciclo siguiente."""
    motor, m15, h4, libro = mundo(tmp_path, n15=30)
    d = str(tmp_path / "estado")
    os.makedirs(d)
    v = verif(tmp_path)
    v.diferir(1, {"BTCUSDT_15m": 1})
    motor.cortado = True
    motor.motivo_corte = "muestra"
    hecho = cerrar_y_publicar(d, motor, m15, h4, libro, v, T0)
    assert hecho["estado"] == "espera"
    assert not os.path.exists(os.path.join(d, C.ARCHIVO_COMPLETADO))
    v.conforme(2, "d", "f")
    assert cerrar_y_publicar(d, motor, m15, h4, libro, v,
                             T0)["estado"] == C.COMPLETADO


def test_el_cierre_administrativo_se_intenta_en_cada_ciclo(tmp_path):
    """CF-35: es un no-op salvo que el reloj pase `T_corte + gracia`."""
    motor, m15, h4, libro = mundo(tmp_path, n15=30)
    d = str(tmp_path / "estado")
    os.makedirs(d)
    v = verif(tmp_path)
    v.conforme(1, "d", "f")
    llamadas = []
    real = type(motor).cerrar_administrativo
    type(motor).cerrar_administrativo = lambda self, r: (
        llamadas.append(r), real(self, r))[1]
    try:
        D.cerrar_si_corresponde(D.BarreraCiclo(), d, IDENT, motor, m15, h4,
                                libro, v, T0)
    finally:
        type(motor).cerrar_administrativo = real
    assert llamadas == [T0]
    assert motor.cortado is False                   # no-op fuera del corte


def test_una_divergencia_real_dispara_BLOCKED_INTEGRITY(tmp_path):
    """Antes la divergencia se marcaba en el sidecar y ahí quedaba."""
    motor, m15, h4, libro = mundo(tmp_path, n15=120)
    d = str(tmp_path / "estado")
    os.makedirs(d)
    v = verif(tmp_path)
    ahora = ahora_de(m15, h4)
    D.ciclo(fetch_reloj(ahora), D.BarreraCiclo(), motor, m15, h4, libro, v,
            lambda: ahora)
    barrera = D.BarreraCiclo()
    with barrera:
        captura = D.capturar(barrera, motor, m15, h4, libro, None,
                             str(tmp_path / "scratch"), ahora, v)
    captura["digest"] = "0" * 64                    # el vivo dijo otra cosa
    resultado = D.verificar_y_reaccionar(
        barrera, captura, v, ahora + 1, d, IDENT, motor, m15, h4, libro,
        commit="ensayo")
    assert resultado["igual"] is False
    assert resultado["terminal"]["estado"] == C.BLOQUEADO
    cuerpo = json.load(open(os.path.join(d, C.ARCHIVO_BLOQUEADO),
                            encoding="utf-8"))
    assert cuerpo["motivo"] == C.MOTIVO_DIVERGENCIA
    assert barrera.terminal                         # no se abren más ciclos


# =============== gates integrados pesados (motor y libro reales) ==========
def test_el_corte_administrativo_NO_se_ejecuta_sin_verificacion_ok(tmp_path):
    """`cerrar_administrativo` EMITE `abierta_al_corte`, `orden_al_corte`,
    `degradacion_de_cobertura` y `corte_administrativo`. Llamarlo con la
    verificación en `pending` reproducía exactamente el cierre científico que
    la zona de corte existe para impedir."""
    motor, m15, h4, libro = mundo(tmp_path, n15=60)
    d = str(tmp_path / "estado")
    os.makedirs(d)
    ahora = ahora_de(m15, h4)
    D.ciclo(fetch_reloj(ahora), D.BarreraCiclo(), motor, m15, h4, libro,
            v_ok := verif(tmp_path), lambda: ahora)
    pasado = T_CORTE + CORTE_ADMIN_GRACIA_MS + 1
    n = len(libro.eventos)

    v = verif(tmp_path, "v2.json")
    v.pendiente(1, "d", "f")
    assert D.cerrar_si_corresponde(D.BarreraCiclo(), d, IDENT, motor, m15, h4,
                                   libro, v, pasado) is None
    assert motor.cortado is False
    assert len(libro.eventos) == n              # NI UN evento nuevo
    for tipo in ("corte_administrativo", "abierta_al_corte", "orden_al_corte",
                 "degradacion_de_cobertura"):
        assert not [e for e in libro.eventos if e["tipo"] == tipo], tipo

    # con `ok`, el corte administrativo REAL sí ocurre y publica COMPLETED
    v.conforme(2, "d", "f")
    hecho = cerrar_y_publicar(d, motor, m15, h4, libro, v, pasado)
    assert motor.cortado is True
    assert hecho["estado"] == C.COMPLETADO
    corte = [e for e in libro.eventos if e["tipo"] == "corte_administrativo"]
    assert corte
    # …y su `processed_at` es el reloj OBSERVADO, no uno que el motor muestreó
    assert corte[0]["processed_at"] == pasado


def test_continuo_N_mas_1_vs_reinicio_da_el_MISMO_libro(tmp_path):
    """El gate central: una corrida continua sobre N+1 velas y otra que
    procesa N, se REINICIA desde los archivos y recibe la vela N+1 tienen que
    producir el mismo libro y el mismo digest."""
    n = 205
    # --- corrida CONTINUA sobre N+1 --------------------------------------
    cont = tmp_path / "continuo"
    cont.mkdir()
    mc, m15c, h4c, libroc = mundo(cont, n15=n + 1)
    ahora = ahora_de(m15c, h4c)
    D.ciclo(fetch_reloj(ahora), D.BarreraCiclo(), mc, m15c, h4c, libroc,
            verif(cont), lambda: 111)

    # --- corrida PARTIDA: N, reinicio, y la vela N+1 ----------------------
    part = tmp_path / "partido"
    part.mkdir()
    mp, m15p, h4p, librop = mundo(part, n15=n)
    D.ciclo(fetch_reloj(ahora_de(m15p, h4p)), D.BarreraCiclo(), mp, m15p, h4p,
            librop, verif(part), lambda: 111)
    # REINICIO real: almacenes y libro se releen desde los archivos
    m15r = {m: S.Almacen.cargar(m, "15m", a.ruta, requerido=True)
            for m, a in m15p.items()}
    h4r = {m: S.Almacen.cargar(m, "4h", a.ruta, requerido=True)
           for m, a in h4p.items()}
    libror = Ledger(librop.ruta, commit="ensayo")
    mr = Motor(m15r, h4r, MERCADOS, libror, bootstrap_hasta=1)
    D.emitir_huecos_locales(mr, m15r, h4r, 111)
    for T in D.cierres_de(m15r, MERCADOS):        # rehidratar el estado
        if not D.procesar_lote_canonico(mr, T, 111):
            break
    # llega la vela N+1: EXACTAMENTE la misma que tuvo la corrida continua
    ult = vela(T0 + n * DUR, 100 + n * 0.1)
    nueva = {(m, "15m"): [[ult["t"], repr(ult["o"]), repr(ult["h"]),
                           repr(ult["l"]), repr(ult["c"]), repr(ult["v"]),
                           ult["t"] + DUR - 1, "0", 0, "0", "0", "0"]]
             for m in MERCADOS}
    D.ciclo(fetch_reloj(ahora + C.MARGEN_CIERRE_MS, nueva), D.BarreraCiclo(),
            mr, m15r, h4r, libror, verif(part, "v2.json"), lambda: 111)

    assert libroc.firma() == libror.firma(), (
        len(libroc.eventos), len(libror.eventos))
    assert (E.observer_state_digest(mc, m15c, h4c, None)
            == E.observer_state_digest(mr, m15r, h4r, None))


def test_caida_entre_el_fsync_del_almacen_y_el_append_al_libro(tmp_path):
    """El marcador queda sellado y durable; el evento no llega. Al reiniciar,
    el marcador ya no vuelve a declararse, así que su evento solo se repone
    porque se emite desde los registros SELLADOS."""
    motor, m15, h4, libro = mundo(tmp_path, n15=60)
    alm = m15["BTCUSDT"]
    alm.ofrecer([vela(alm.ultimo_t + (2 + i) * DUR) for i in range(4)], "push")
    alm.drenar()
    assert alm.declarar_hueco_local() is not None      # sellado y durable
    alm.sincronizar()

    # CAÍDA: el append al libro revienta justo después
    real = Ledger.append
    def caer(self, tipo, **campos):
        if tipo == "hueco_detectado":
            raise OSError(28, "ENOSPC")
        return real(self, tipo, **campos)
    Ledger.append = caer
    try:
        with pytest.raises(OSError):
            D.emitir_huecos_locales(motor, m15, h4, 111)
    finally:
        Ledger.append = real
    assert not [e for e in libro.eventos if e["tipo"] == "hueco_detectado"]

    # REINICIO: el marcador ya está sellado y no se vuelve a declarar
    m15r = {m: S.Almacen.cargar(m, "15m", a.ruta, requerido=True)
            for m, a in m15.items()}
    h4r = {m: S.Almacen.cargar(m, "4h", a.ruta, requerido=True)
           for m, a in h4.items()}
    assert m15r["BTCUSDT"].declarar_hueco_local() is None
    libror = Ledger(libro.ruta, commit="ensayo")
    mr = Motor(m15r, h4r, MERCADOS, libror, bootstrap_hasta=1)
    D.emitir_huecos_locales(mr, m15r, h4r, 111)
    for T in D.cierres_de(m15r, MERCADOS):
        if not D.procesar_lote_canonico(mr, T, 111):
            break

    # --- y la CORRIDA CONTINUA equivalente, sin la caída -----------------
    cont = tmp_path / "continuo"
    cont.mkdir()
    mc, m15c, h4c, libroc = mundo(cont, n15=60)
    almc = m15c["BTCUSDT"]
    almc.ofrecer([vela(almc.ultimo_t + (2 + i) * DUR) for i in range(4)],
                 "push")
    almc.drenar()
    assert almc.declarar_hueco_local() is not None
    almc.sincronizar()
    D.emitir_huecos_locales(mc, m15c, h4c, 111)
    for T in D.cierres_de(m15c, MERCADOS):
        if not D.procesar_lote_canonico(mc, T, 111):
            break

    # equivalencia COMPLETA, no solo «reapareció el evento»
    for m in MERCADOS:
        assert m15r[m].head == m15c[m].head, m
        assert h4r[m].head == h4c[m].head, m
    assert libror.firma() == libroc.firma()
    assert ([E.canon(e) for e in libror.eventos]
            == [E.canon(e) for e in libroc.eventos])
    assert (E.observer_state_digest(mr, m15r, h4r, None)
            == E.observer_state_digest(mc, m15c, h4c, None))
    huecos = [e for e in libror.eventos if e["tipo"] == "hueco_detectado"]
    assert huecos and huecos[0]["motivo"] == "local"


def test_el_cierre_50_lo_produce_el_motor_y_dispara_el_corte(tmp_path):
    """Camino real `49 → cierre 50 por la ruta del motor → _fase8 → COMPLETED`.

    El PREFIJO de 49 cierres se prepara canónicamente —sintetizar 49 trades
    completos con datos planos no es viable—, pero el cierre 50 lo produce el
    motor: se le deja una POSICIÓN viva cuyo objetivo toca la vela siguiente,
    y Fase 1a la cierra por `evaluar_salida` → `_cerrar_posicion` →
    `cierres.append` → `_fase8` → `_cerrar("muestra", T)`.
    """
    from modules.bot3.v9.contract import CORTE_MIN_SEMANAS_ISO
    motor, m15, h4, libro = mundo(tmp_path, n15=210)
    d = str(tmp_path / "estado")
    os.makedirs(d)
    v = verif(tmp_path)
    v.conforme(1, "d", "f")

    # 49 cierres repartidos en semanas ISO suficientes: uno MENOS que el corte
    semana = 7 * 24 * 3600 * 1000
    motor.cierres = [{"t": T0 - (49 - i) * semana // 2, "mercado": "BTCUSDT",
                      "r": 0.1, "trade_id": f"t{i}"} for i in range(49)]
    assert len(motor.cierres) == CORTE_N_CIERRES - 1
    assert len({motor._semana_iso(c["t"]) for c in motor.cierres}) >= \
        CORTE_MIN_SEMANAS_ISO

    # Primero se procesa la historia, para que la ÉPOCA quede habilitada:
    # Fase 1a solo corre dentro de una época vigente (≥200 velas).
    ahora = ahora_de(m15, h4)
    D.ciclo(fetch_reloj(ahora), D.BarreraCiclo(), motor, m15, h4, libro, v,
            lambda: ahora, estado_dir=d, identidad=IDENT)
    assert motor.cortado is False

    # posición viva cuyo OBJETIVO toca la vela NUEVA que llega ahora
    t_nueva = m15["BTCUSDT"].ultimo_t + DUR
    nueva = vela(t_nueva, 100 + 210 * 0.1)
    objetivo = nueva["h"] - 0.2                    # dentro del rango
    st = motor.estados["BTCUSDT"]
    st.posicion = {"order_id": "o-50", "candidate_id": "c-50",
                   "E": nueva["o"], "S": nueva["l"] - 10, "T": objetivo,
                   "largo": True, "dir": "long",
                   "deadline_close": t_nueva + 100 * DUR,
                   "P_in": nueva["o"], "trade_id": "trade-50",
                   "close_fill": m15["BTCUSDT"].ultimo_t,
                   "ultimo_cierre_sellado": m15["BTCUSDT"].ultimo_t}
    st.estado = "posicion"

    paginas = {(m, "15m"): [[nueva["t"], repr(nueva["o"]), repr(nueva["h"]),
                             repr(nueva["l"]), repr(nueva["c"]),
                             repr(nueva["v"]), nueva["t"] + DUR - 1,
                             "0", 0, "0", "0", "0"]] for m in MERCADOS}
    ahora2 = t_nueva + DUR + C.MARGEN_CIERRE_MS
    parte = D.ciclo(fetch_reloj(ahora2, paginas), D.BarreraCiclo(), motor, m15,
                    h4, libro, v, lambda: ahora2, estado_dir=d,
                    identidad=IDENT)

    # el cierre 50 lo emitió el MOTOR, y ese cierre disparó el corte
    cerrados = [e for e in libro.eventos if e["tipo"] == "cerrado"]
    assert len(cerrados) == 1 and cerrados[0]["id"] == "trade-50"
    assert len(motor.cierres) == CORTE_N_CIERRES
    assert motor.cortado is True and motor.motivo_corte == "muestra"
    assert parte["terminal"]["estado"] == C.COMPLETADO
    cuerpo = json.load(open(os.path.join(d, C.ARCHIVO_COMPLETADO),
                            encoding="utf-8"))
    assert cuerpo["motivo"] == "muestra"

    # no hay eventos 51+
    n = len(libro.eventos)
    otro = D.ciclo(fetch_reloj(ahora2), D.BarreraCiclo(), motor, m15, h4, libro,
                   v, lambda: ahora2, estado_dir=d, identidad=IDENT)
    assert otro["procesados"] == []
    assert len(libro.eventos) == n
    assert len(motor.cierres) == CORTE_N_CIERRES

    # REINICIO con objetos NUEVOS, rehidratados desde disco
    m15r = {m: S.Almacen.cargar(m, "15m", a.ruta, requerido=True)
            for m, a in m15.items()}
    h4r = {m: S.Almacen.cargar(m, "4h", a.ruta, requerido=True)
           for m, a in h4.items()}
    libror = Ledger(libro.ruta, commit="ensayo")
    mr = Motor(m15r, h4r, MERCADOS, libror, bootstrap_hasta=1)
    fresca = D.BarreraCiclo()
    leido = D.reanudar(fresca, d, IDENT, mr, m15r, h4r, libror, ahora2)
    assert leido["estado"] == C.COMPLETADO
    assert fresca.terminal
    antes = len(libror.eventos)
    assert D.ciclo(fetch_reloj(ahora2), fresca, mr, m15r, h4r, libror,
                   v, lambda: ahora2)["ingirio"] is False
    assert len(libror.eventos) == antes


def test_un_corte_cientifico_se_reanuda_como_COMPLETED_no_como_BLOCKED(
        tmp_path):
    """`reanudar` publicaba con el default `BLOQUEADO`: una caída después de
    registrar un corte `muestra` y antes de publicarlo reiniciaba como
    `BLOCKED_INTEGRITY` — un corte legítimo convertido en fallo de
    integridad. El terminal se DERIVA del motivo ganador."""
    assert D.estado_final_de("muestra") == C.COMPLETADO
    assert D.estado_final_de("administrativo") == C.COMPLETADO
    assert D.estado_final_de(C.MOTIVO_SILENCIO) == C.BLOQUEADO
    assert D.estado_final_de(C.MOTIVO_DIVERGENCIA) == C.BLOQUEADO

    motor, m15, h4, libro = mundo(tmp_path, n15=30)
    d = str(tmp_path / "estado")
    os.makedirs(d)
    barrera = D.BarreraCiclo()
    # el sidecar vive en `estado_dir`: la reanudación lo RECARGA de disco, no
    # confía en un objeto en memoria que la caída perdió
    v = E.Verificacion(os.path.join(d, C.ARCHIVO_VERIFICACION))
    v.conforme(1, "d", "f")
    # CAÍDA: la causa quedó anotada y no se publicó
    D.registrar_causa(barrera, d, "muestra", IDENT, {"cierres": 50}, T0,
                      m15, h4, libro)
    assert not os.path.exists(os.path.join(d, C.ARCHIVO_COMPLETADO))
    hecho = D.reanudar(D.BarreraCiclo(), d, IDENT, motor, m15, h4, libro, T0)
    assert hecho["estado"] == C.COMPLETADO
    assert os.path.exists(os.path.join(d, C.ARCHIVO_COMPLETADO))
    assert not os.path.exists(os.path.join(d, C.ARCHIVO_BLOQUEADO))


def test_una_divergencia_entre_registro_y_publicacion_impide_COMPLETED(
        tmp_path):
    """La ventana que abría la ruta de dos fases: el corte se anota, y ANTES
    de publicar la verificación pasa a `divergent`.

    §9.1.2, regla PREVIA E INCONDICIONAL: quien entra en la fase B y ve
    `divergent` ANEXA `determinism_divergence` con su evidencia antes de
    calcular el ganador, y publica `BLOCKED_INTEGRITY` en esa misma pasada.
    Esperar acá —lo que hacía rev.12— dejaba la condición inobservable: entre
    que la comparación fría escribe el sidecar y pide la barrera, otra fase B
    podía dar la ventana por cerrada y publicar el ganador anterior."""
    motor, m15, h4, libro = mundo(tmp_path, n15=30)
    d = str(tmp_path / "estado")
    os.makedirs(d)
    v = verif(tmp_path)
    v.conforme(1, "d", "f")
    barrera = D.BarreraCiclo()
    D.registrar_causa(barrera, d, "muestra", IDENT, {"cierres": 50}, T0,
                      m15, h4, libro)
    v.divergente(2, {"esperado": 1}, {"obtenido": 2})   # llega la divergencia
    hecho = D.publicar_pendiente(barrera, d, T0, motor, m15, h4, libro, v,
                                 IDENT)
    assert hecho["estado"] == C.BLOQUEADO
    assert hecho["cuerpo"]["motivo"] == C.MOTIVO_DIVERGENCIA
    # la evidencia publicada es la de la DIVERGENCIA, no la del corte
    assert hecho["cuerpo"]["evidencia"] == v.detalle
    assert hecho["cuerpo"]["motivos_adicionales"] == ["muestra"]
    assert not os.path.exists(os.path.join(d, C.ARCHIVO_COMPLETADO))
    assert hecho["cuerpo"]["motivo"] == C.MOTIVO_DIVERGENCIA
    assert "muestra" in hecho["cuerpo"]["motivos_adicionales"]


def test_el_estado_autorizado_se_refresca_con_cada_causa(tmp_path):
    """Si la primera causa lo fija y una segunda mueve el libro, el request
    habría autorizado un estado ya viejo y la reanudación lo habría rechazado
    por divergencia de heads/firma."""
    motor, m15, h4, libro = mundo(tmp_path, n15=30)
    d = str(tmp_path / "estado")
    os.makedirs(d)
    ruta = os.path.join(d, C.ARCHIVO_SOLICITUD_TERMINAL)
    sidecar_ok(d)
    barrera = D.BarreraCiclo()
    D.registrar_causa(barrera, d, C.MOTIVO_SILENCIO, IDENT, {}, T0,
                      m15, h4, libro)
    primero = json.load(open(ruta, encoding="utf-8"))["estado_esperado"]
    # entre una causa y otra, el libro se mueve
    libro.append("lote_finalizado", effective_at=T0, finalized_at=T0)
    D.registrar_causa(barrera, d, C.MOTIVO_DIVERGENCIA, IDENT, {}, T0 + 1,
                      m15, h4, libro)
    segundo = json.load(open(ruta, encoding="utf-8"))["estado_esperado"]
    assert segundo != primero
    assert segundo["firma"] == libro.firma()
    # y por eso la reanudación NO lo rechaza
    hecho = D.reanudar(D.BarreraCiclo(), d, IDENT, motor, m15, h4, libro,
                       T0 + 2)
    assert hecho["estado"] == C.BLOQUEADO


# ============ gates 40..40quinquies — transición terminal (rev.16) ==========
def _estado_dir(tmp_path, nombre="estado"):
    d = str(tmp_path / nombre)
    os.makedirs(d, exist_ok=True)
    return d


def test_g40_estado_esperado_alterado_falla_cerrado(tmp_path):
    """§13.4: el request AUTORIZA un estado concreto. Publicar sobre otro sería
    cerrar la cohorte con heads, firma o sidecars distintos de los que se
    autorizaron. Las tres alteraciones, por separado."""
    for i, romper in enumerate((
            lambda m15, h4, libro, d: m15["BTCUSDT"].ofrecer(
                [vela(m15["BTCUSDT"].ultimo_t + DUR)], "push")
            or m15["BTCUSDT"].drenar(),
            lambda m15, h4, libro, d: libro.append(
                "lote_finalizado", effective_at=T0, finalized_at=T0),
            lambda m15, h4, libro, d: E.escribir_atomico(
                os.path.join(d, C.ARCHIVO_SILENCIO), '{"x": 1}'),
    )):
        motor, m15, h4, libro = mundo(tmp_path / f"g40_{i}", n15=30)
        d = _estado_dir(tmp_path / f"g40_{i}")
        v = verif(tmp_path / f"g40_{i}")
        v.conforme(1, "d", "f")
        barrera = D.BarreraCiclo()
        D.registrar_causa(barrera, d, "muestra", IDENT, {"cierres": 50}, T0,
                          m15, h4, libro)
        romper(m15, h4, libro, d)                  # el mundo se movió
        with pytest.raises(ValueError, match="autoriza otro estado"):
            D.publicar_pendiente(barrera, d, T0, motor, m15, h4, libro, v,
                                 IDENT)
        assert not os.path.exists(os.path.join(d, C.ARCHIVO_COMPLETADO))


def test_g40_matriz_de_reanudacion_completa(tmp_path):
    """§13.5, fila por fila. Cada celda se ejerce contra el `Motor` real."""
    def escenario(nombre, motivo, preparar):
        motor, m15, h4, libro = mundo(tmp_path / nombre, n15=30)
        d = _estado_dir(tmp_path / nombre)
        v = E.Verificacion(os.path.join(d, C.ARCHIVO_VERIFICACION))
        preparar(v)
        D.registrar_causa(D.BarreraCiclo(), d, motivo, IDENT, {"e": 1}, T0,
                          m15, h4, libro)
        return d, motor, m15, h4, libro

    # `ok` y posterior a toda deferencia → COMPLETED
    d, *mundo_ok = escenario("ok", "muestra",
                             lambda v: v.conforme(2, "d", "f"))
    assert D.reanudar(D.BarreraCiclo(), d, IDENT, *mundo_ok,
                      T0)["estado"] == C.COMPLETADO

    # `pending` con la copia AUSENTE → fallo cerrado: no se puede ni
    # certificar ni descartar el determinismo
    d, *mp = escenario("pend", "muestra", lambda v: v.pendiente(
        2, "d", "f", "/no/existe"))
    with pytest.raises(ValueError, match="copia no existe"):
        D.reanudar(D.BarreraCiclo(), d, IDENT, *mp, T0)

    # `deferred` con ganador CIENTÍFICO → fallo cerrado (§13.5.0)
    d, *md = escenario("defc", "muestra", lambda v: v.diferir(2, {"b": 1}))
    with pytest.raises(ValueError, match="inalcanzable"):
        D.reanudar(D.BarreraCiclo(), d, IDENT, *md, T0)

    # `deferred` con ganador de INTEGRIDAD → se PUBLICA (rev.13)
    d, *mi = escenario("defi", C.MOTIVO_SILENCIO, lambda v: v.diferir(2, {}))
    assert D.reanudar(D.BarreraCiclo(), d, IDENT, *mi,
                      T0)["estado"] == C.BLOQUEADO

    # `divergent` → se ANEXA la divergencia y se publica BLOCKED_INTEGRITY
    d, *mv = escenario("div", "muestra",
                       lambda v: v.divergente(2, {"a": 1}, {"a": 2}))
    hecho = D.reanudar(D.BarreraCiclo(), d, IDENT, *mv, T0)
    assert hecho["estado"] == C.BLOQUEADO
    assert hecho["cuerpo"]["motivo"] == C.MOTIVO_DIVERGENCIA
    assert hecho["cuerpo"]["motivos_adicionales"] == ["muestra"]

    # sidecar AUSENTE con ganador científico → fallo cerrado
    d, *ma = escenario("aus", "muestra", lambda v: None)
    with pytest.raises(ValueError, match="sin .*verificacion.json"):
        D.reanudar(D.BarreraCiclo(), d, IDENT, *ma, T0)

    # request de OTRA identidad → fallo cerrado
    d, *mo = escenario("ident", "muestra", lambda v: v.conforme(2, "d", "f"))
    with pytest.raises(ValueError, match="otra cohorte"):
        D.reanudar(D.BarreraCiclo(), d, dict(IDENT, cohorte="otra"), *mo, T0)


def test_g40bis_la_ventana_admite_una_segunda_causa_y_prohibe_ciclos(tmp_path):
    """Un registrador B entra DESPUÉS de A y ANTES de publicar, con el mutex
    REAL. Y mientras la ventana está abierta, ningún ciclo de ingesta entra."""
    motor, m15, h4, libro = mundo(tmp_path, n15=30)
    d = _estado_dir(tmp_path)
    v = verif(tmp_path)
    v.conforme(1, "d", "f")
    barrera = D.BarreraCiclo()

    D.registrar_causa(barrera, d, "muestra", IDENT, {"cierres": 50}, T0,
                      m15, h4, libro)               # A
    assert barrera.cierre_en_curso is True
    # ningún ciclo abre en la ventana: una captura suya podría producir la
    # deferencia que §13.5.0 declara inalcanzable
    heads = {m: a.head for m, a in m15.items()}
    ahora = ahora_de(m15, h4)
    parte = D.ciclo(fetch_reloj(ahora), barrera, motor, m15, h4, libro, v,
                    lambda: ahora, estado_dir=d, identidad=IDENT)
    assert parte["ingirio"] is False
    assert "cierre en curso" in parte["motivo"]
    assert {m: a.head for m, a in m15.items()} == heads

    D.registrar_causa(barrera, d, C.MOTIVO_DIVERGENCIA, IDENT, {"x": 1},
                      T0 + 1, m15, h4, libro)       # B, en la misma ventana
    hecho = D.publicar_pendiente(barrera, d, T0 + 1, motor, m15, h4, libro, v,
                                 IDENT)
    assert hecho["cuerpo"]["motivo"] == C.MOTIVO_DIVERGENCIA
    assert hecho["cuerpo"]["evidencia"] == {"x": 1}


def test_g40ter_la_ventana_se_cierra_por_GANADOR(tmp_path):
    """§9.1.2, celda por celda."""
    # `determinism_divergence` publica aunque la comparación siga `pending`
    assert D.ventana_cerrada(C.MOTIVO_DIVERGENCIA,
                             _v(C.VERIF_PENDIENTE)) is True
    # `silencio_h4` con `pending` ESPERA; con `deferred` u `ok` PUBLICA
    assert D.ventana_cerrada(C.MOTIVO_SILENCIO, _v(C.VERIF_PENDIENTE)) is False
    assert D.ventana_cerrada(C.MOTIVO_SILENCIO, _v(C.VERIF_DIFERIDA)) is True
    assert D.ventana_cerrada(C.MOTIVO_SILENCIO, _v(C.VERIF_OK)) is True
    # científico: `pending` espera, `deferred` falla cerrado
    for m in C.MOTIVOS_CIENTIFICOS:
        assert D.ventana_cerrada(m, _v(C.VERIF_PENDIENTE)) is False
        with pytest.raises(ValueError, match="inalcanzable"):
            D.ventana_cerrada(m, _v(C.VERIF_DIFERIDA))
    # y un motivo que nadie definió no cierra nada
    with pytest.raises(ValueError, match="registro cerrado"):
        D.ventana_cerrada("n_cierres", _v(C.VERIF_OK))


def _v(estado):
    v = E.Verificacion("/dev/null")
    v.estado = estado
    v.ultima_ok = {"instante": 10, "digest": "d", "firma": "f"}
    return v


def test_g40ter_la_fase_B_anexa_la_divergencia_que_observa(tmp_path):
    """La carrera REAL: la comparación fría escribe `verificacion.json` y
    recién después pide la barrera. Entre esos dos pasos, la fase B veía
    `divergent`, daba la ventana por cerrada y publicaba el `silencio_h4`
    anterior sin que la divergencia llegara nunca al request."""
    motor, m15, h4, libro = mundo(tmp_path, n15=30)
    d = _estado_dir(tmp_path)
    v = verif(tmp_path)
    v.conforme(1, "d", "f")
    barrera = D.BarreraCiclo()
    D.registrar_causa(barrera, d, C.MOTIVO_SILENCIO, IDENT, {"h": 72}, T0,
                      m15, h4, libro)
    # el sidecar YA está divergente; el registro de la causa todavía NO ocurrió
    v.divergente(2, {"a": 1}, {"a": 2})
    hecho = D.publicar_pendiente(barrera, d, T0, motor, m15, h4, libro, v,
                                 IDENT)
    assert hecho["cuerpo"]["motivo"] == C.MOTIVO_DIVERGENCIA
    assert hecho["cuerpo"]["evidencia"] == v.detalle
    assert hecho["cuerpo"]["motivos_adicionales"] == [C.MOTIVO_SILENCIO]


def test_g40ter_la_comparacion_fria_dispara_la_fase_B_al_terminar(tmp_path):
    """§9.1.3, segundo disparador. Al pasar de `pending` a `ok` no hay causa
    nueva que registrar: sin este disparador nadie volvería a publicar y la
    cohorte quedaba detenida con la ventana abierta, porque los ciclos están
    prohibidos justamente ahí."""
    motor, m15, h4, libro = mundo(tmp_path, n15=210)
    d = _estado_dir(tmp_path)
    v = E.Verificacion(os.path.join(d, C.ARCHIVO_VERIFICACION))
    ahora = ahora_de(m15, h4)
    D.ciclo(fetch_reloj(ahora), D.BarreraCiclo(), motor, m15, h4, libro, v,
            lambda: ahora)
    barrera = D.BarreraCiclo()
    with barrera:                       # la captura exige la barrera RETENIDA
        captura = D.capturar(barrera, motor, m15, h4, libro, None,
                             str(tmp_path / "scratch"), ahora, v)
    D.registrar_causa(barrera, d, "muestra", IDENT, {"cierres": 50}, ahora,
                      m15, h4, libro)
    assert v.estado == C.VERIF_PENDIENTE
    # la ventana NO cierra mientras la comparación corre
    assert D.publicar_pendiente(barrera, d, ahora, motor, m15, h4, libro, v,
                                IDENT)["estado"] == "espera"
    # y al terminar CONFORME, la propia comparación publica
    res = D.verificar_y_reaccionar(barrera, captura, v, ahora, d, IDENT,
                                   motor, m15, h4, libro, commit="ensayo")
    assert res["igual"] is True and v.estado == C.VERIF_OK
    assert res["terminal"]["estado"] == C.COMPLETADO
    assert res["terminal"]["cuerpo"]["motivo"] == "muestra"


def test_g40quinquies_el_arranque_dispara_la_fase_B_y_no_ingiere(tmp_path):
    """§9.1.3, tercer disparador. Una caída entre registrar y publicar dejaba
    el request sin nadie que lo retomara.

    La exigencia es de EQUIVALENCIA: el reinicio produce exactamente el mismo
    terminal que la corrida que no se cayó — mismo motivo, misma evidencia,
    mismos heads y misma firma."""
    def preparar(nombre):
        motor, m15, h4, libro = mundo(tmp_path / nombre, n15=30)
        d = _estado_dir(tmp_path / nombre)
        v = E.Verificacion(os.path.join(d, C.ARCHIVO_VERIFICACION))
        v.conforme(1, "d", "f")
        D.registrar_causa(D.BarreraCiclo(), d, "muestra", IDENT,
                          {"cierres": 50}, T0, m15, h4, libro)
        return d, motor, m15, h4, libro, v

    # (a) corrida CONTINUA: la misma barrera publica
    d_a, motor_a, m15_a, h4_a, libro_a, v_a = preparar("continua")
    continua = D.publicar_pendiente(D.BarreraCiclo(), d_a, T0, motor_a, m15_a,
                                    h4_a, libro_a, v_a, IDENT)

    # (b) CAÍDA: proceso nuevo, barrera nueva, sidecar recargado de disco
    d_b, motor_b, m15_b, h4_b, libro_b, _ = preparar("caida")
    barrera = D.BarreraCiclo()
    ahora = ahora_de(m15_b, h4_b)
    reanudado = D.reanudar(barrera, d_b, IDENT, motor_b, m15_b, h4_b, libro_b,
                           T0)
    assert reanudado["reanudado"] is True
    assert reanudado["estado"] == continua["estado"] == C.COMPLETADO

    for campo in ("motivo", "evidencia", "heads", "firma",
                  "motivos_adicionales"):
        assert reanudado["cuerpo"][campo] == continua["cuerpo"][campo]

    # el arranque NO ingirió: ningún ciclo se abrió antes de la fase B
    assert barrera.terminal == "muestra"
    heads = {m: a.head for m, a in m15_b.items()}
    parte = D.ciclo(fetch_reloj(ahora), barrera, motor_b, m15_b, h4_b, libro_b,
                    verif(tmp_path / "caida"), lambda: ahora, estado_dir=d_b,
                    identidad=IDENT)
    assert parte["ingirio"] is False
    assert {m: a.head for m, a in m15_b.items()} == heads
    # y el request ya no está: cumplió su función
    assert not os.path.exists(os.path.join(d_b, C.ARCHIVO_SOLICITUD_TERMINAL))


def test_g40quater_borrar_vs_archivar_el_request(tmp_path):
    """§12: borrado en el flujo normal; ARCHIVADO cuando es un residual
    coincidente tras caída; fallo cerrado si discrepa."""
    # (a) flujo normal → BORRADO
    motor, m15, h4, libro = mundo(tmp_path / "normal", n15=30)
    d = _estado_dir(tmp_path / "normal")
    v = verif(tmp_path / "normal")
    v.conforme(1, "d", "f")
    E.escribir_atomico(os.path.join(d, C.ARCHIVO_PEDIDO_VERIFICACION), "{}")
    barrera = D.BarreraCiclo()
    D.registrar_causa(barrera, d, "muestra", IDENT, {"c": 50}, T0, m15, h4,
                      libro)
    D.publicar_pendiente(barrera, d, T0, motor, m15, h4, libro, v, IDENT)
    assert not os.path.exists(os.path.join(d, C.ARCHIVO_SOLICITUD_TERMINAL))
    # el verify.request no atendido se ARCHIVA con el terminal
    assert not os.path.exists(os.path.join(d, C.ARCHIVO_PEDIDO_VERIFICACION))
    assert os.path.exists(
        os.path.join(d, C.ARCHIVO_PEDIDO_VERIFICACION + ".archivado"))

    # (b) caída ENTRE publicar y borrar → residual COINCIDENTE, se ARCHIVA
    motor2, m15b, h4b, librob = mundo(tmp_path / "residual", n15=30)
    d2 = _estado_dir(tmp_path / "residual")
    v2 = E.Verificacion(os.path.join(d2, C.ARCHIVO_VERIFICACION))
    v2.conforme(1, "d", "f")
    D.registrar_causa(D.BarreraCiclo(), d2, "muestra", IDENT, {"c": 50}, T0,
                      m15b, h4b, librob)
    E.publicar_terminal(d2, C.COMPLETADO, dict(
        IDENT, motivo="muestra", evidencia={"c": 50},
        heads=E.estado_almacenes(m15b, h4b), firma=librob.firma()))
    barrera2 = D.BarreraCiclo()
    hecho = D.reanudar(barrera2, d2, IDENT, motor2, m15b, h4b, librob, T0)
    assert hecho["ya_existia"] is True
    assert barrera2.cierre_en_curso is False
    assert not os.path.exists(os.path.join(d2, C.ARCHIVO_SOLICITUD_TERMINAL))
    assert os.path.exists(
        os.path.join(d2, C.ARCHIVO_SOLICITUD_TERMINAL + ".archivado"))

    # (c) residual DISCREPANTE → fallo cerrado, y nada se archiva
    motor3, m15c, h4c, libroc = mundo(tmp_path / "discrepa", n15=30)
    d3 = _estado_dir(tmp_path / "discrepa")
    D.registrar_causa(D.BarreraCiclo(), d3, C.MOTIVO_SILENCIO, IDENT, {},
                      T0, m15c, h4c, libroc)
    E.publicar_terminal(d3, C.COMPLETADO, dict(IDENT, motivo="muestra"))
    with pytest.raises(ValueError, match="no deriva del ganador"):
        D.reanudar(D.BarreraCiclo(), d3, IDENT, motor3, m15c, h4c, libroc, T0)
    assert os.path.exists(os.path.join(d3, C.ARCHIVO_SOLICITUD_TERMINAL))


def test_g40_el_sidecar_de_verificacion_no_puede_estar_en_el_estado(tmp_path):
    """§13.4 pide «el hash de CADA sidecar», pero §9.1.3 hace que la
    comparación fría REESCRIBA `verificacion.json` al pasar de `pending` a
    `ok` — y ese es el disparador normal de la fase B.

    Las dos cláusulas juntas hacen inalcanzable la ruta principal: el request
    autoriza el hash de `pending` y la publicación encuentra el de `ok`. Este
    gate fija la lectura que mantiene viva la máquina —el estado autorizado
    cubre lo que DECIDE el terminal, no la compuerta que lo habilita— y falla
    si alguien vuelve a meter la verificación adentro."""
    motor, m15, h4, libro = mundo(tmp_path, n15=30)
    d = _estado_dir(tmp_path)
    v = E.Verificacion(os.path.join(d, C.ARCHIVO_VERIFICACION))
    v.pendiente(1, "d", "f", str(tmp_path / "copia"))
    antes = D.estado_esperado(d, m15, h4, libro)
    v.conforme(2, "d", "f")                     # la comparación termina
    assert D.estado_esperado(d, m15, h4, libro) == antes
    assert C.ARCHIVO_VERIFICACION not in antes["sidecars"]
    # el silencio SÍ está: su evidencia decide el terminal
    E.escribir_atomico(os.path.join(d, C.ARCHIVO_SILENCIO), '{"x": 1}')
    assert C.ARCHIVO_SILENCIO in D.estado_esperado(d, m15, h4,
                                                   libro)["sidecars"]


def test_g40quater_el_orden_del_final_del_ciclo_es_normativo(tmp_path):
    """§12: corte número 50 y un `verify.request` pendiente en el MISMO ciclo,
    con buffers NO vacíos.

    Con el orden anterior —atender el pedido y recién después registrar— esta
    secuencia era legítima y trababa la cohorte: la captura encontraba
    buffers, la verificación pasaba a `deferred`, y la causa científica se
    registraba encima. `deferred` con ganador científico es justo el estado
    que §13.5.0 declara inalcanzable.

    Se exige además que no haya READQUISICIÓN del mutex dentro del ciclo —una
    implementación literal de rev.14 hacía deadlock— y que la fase B se invoque
    DESPUÉS de liberar la barrera.
    """
    from modules.bot3.v9.contract import CORTE_MIN_SEMANAS_ISO
    motor, m15, h4, libro = mundo(tmp_path, n15=210)
    d = _estado_dir(tmp_path)
    v = E.Verificacion(os.path.join(d, C.ARCHIVO_VERIFICACION))
    v.conforme(1, "d", "f")
    semana = 7 * 24 * 3600 * 1000
    motor.cierres = [{"t": T0 - (49 - i) * semana // 2, "mercado": "BTCUSDT",
                      "r": 0.1, "trade_id": f"t{i}"} for i in range(49)]
    assert len({motor._semana_iso(c["t"]) for c in motor.cierres}) >= \
        CORTE_MIN_SEMANAS_ISO

    ahora = ahora_de(m15, h4)
    D.ciclo(fetch_reloj(ahora), D.BarreraCiclo(), motor, m15, h4, libro, v,
            lambda: ahora, estado_dir=d, identidad=IDENT)
    assert motor.cortado is False

    t_nueva = m15["BTCUSDT"].ultimo_t + DUR
    nueva = vela(t_nueva, 100 + 210 * 0.1)
    st = motor.estados["BTCUSDT"]
    st.posicion = {"order_id": "o-50", "candidate_id": "c-50",
                   "E": nueva["o"], "S": nueva["l"] - 10,
                   "T": nueva["h"] - 0.2, "largo": True, "dir": "long",
                   "deadline_close": t_nueva + 100 * DUR,
                   "P_in": nueva["o"], "trade_id": "trade-50",
                   "close_fill": m15["BTCUSDT"].ultimo_t,
                   "ultimo_cierre_sellado": m15["BTCUSDT"].ultimo_t}
    st.estado = "posicion"
    paginas = {(m, "15m"): [[nueva["t"], repr(nueva["o"]), repr(nueva["h"]),
                             repr(nueva["l"]), repr(nueva["c"]),
                             repr(nueva["v"]), nueva["t"] + DUR - 1,
                             "0", 0, "0", "0", "0"]] for m in MERCADOS}

    # el pedido de verificación llega ANTES del ciclo que corta...
    E.escribir_atomico(os.path.join(d, C.ARCHIVO_PEDIDO_VERIFICACION), "{}")
    # ...y hay buffers NO vacíos: atenderlo produciría `deferred`
    h4["BTCUSDT"].ofrecer([vela(h4["BTCUSDT"].ultimo_t + 9 * DUR4)], "push")
    assert D.buffers_no_vacios(m15, h4)

    # la barrera REAL, observada: nunca se readquiere dentro del ciclo
    barrera = D.BarreraCiclo()
    adquisiciones = []
    lock_real = barrera._lock

    class LockObservado:
        def acquire(self, *a, **k):
            adquisiciones.append(("acquire", barrera.retenida))
            return lock_real.acquire(*a, **k)

        def release(self):
            adquisiciones.append(("release", None))
            return lock_real.release()

    barrera._lock = LockObservado()
    ahora2 = t_nueva + DUR + C.MARGEN_CIERRE_MS
    parte = D.ciclo(fetch_reloj(ahora2, paginas), barrera, motor, m15, h4,
                    libro, v, lambda: ahora2, estado_dir=d, identidad=IDENT)

    # el corte ocurrió y el terminal se publicó
    assert motor.cortado is True and motor.motivo_corte == "muestra"
    assert parte["causas"] == ["muestra"]
    assert parte["terminal"]["estado"] == C.COMPLETADO

    # la causa se registró ANTES: no se creó ninguna deferencia nueva y la
    # verificación conserva el estado que tenía
    assert v.estado == C.VERIF_OK
    assert v.ultima_deferencia is None
    assert parte.get("captura") is None

    # el verify.request quedó SIN atender y se ARCHIVA con el terminal
    assert not os.path.exists(os.path.join(d, C.ARCHIVO_PEDIDO_VERIFICACION))
    assert os.path.exists(
        os.path.join(d, C.ARCHIVO_PEDIDO_VERIFICACION + ".archivado"))
    assert not os.path.exists(os.path.join(d, C.ARCHIVO_SOLICITUD_TERMINAL))

    # NINGUNA adquisición ocurrió con la barrera ya retenida —eso es el
    # deadlock— y la fase B corrió DESPUÉS de liberar la del ciclo
    assert not any(retenida for accion, retenida in adquisiciones
                   if accion == "acquire" and retenida)
    ciclo_libera = adquisiciones.index(("release", None))
    assert ("acquire", False) in adquisiciones[ciclo_libera + 1:]


def _mundo_con_captura(tmp_path, nombre):
    """Motor real, un ciclo procesado, captura tomada y causa científica
    registrada mientras la comparación está `pending`."""
    motor, m15, h4, libro = mundo(tmp_path / nombre, n15=210)
    d = _estado_dir(tmp_path / nombre)
    v = E.Verificacion(os.path.join(d, C.ARCHIVO_VERIFICACION))
    ahora = ahora_de(m15, h4)
    D.ciclo(fetch_reloj(ahora), D.BarreraCiclo(), motor, m15, h4, libro, v,
            lambda: ahora)
    barrera = D.BarreraCiclo()
    with barrera:
        captura = D.capturar(barrera, motor, m15, h4, libro, None,
                             str(tmp_path / nombre / "scratch"), ahora, v)
    assert v.estado == C.VERIF_PENDIENTE
    D.registrar_causa(barrera, d, "muestra", IDENT, {"cierres": 50}, ahora,
                      m15, h4, libro, verificacion=v)
    return d, motor, m15, h4, libro, v, captura, ahora


def test_g40quinquies_el_arranque_con_pending_COMPLETA_la_comparacion(tmp_path):
    """§13.5.1 + §9.1.3: quedarse esperando era detener la cohorte para
    siempre.

    La comparación fría no es un ciclo y nadie más la retoma — los ciclos
    están prohibidos durante la ventana, precisamente—, así que el ARRANQUE la
    reconstruye desde la copia guardada en el sidecar, la COMPLETA y publica.
    La exigencia es de EQUIVALENCIA con la corrida que no se cayó."""
    # (a) corrida CONTINUA: la comparación termina en el mismo proceso
    d_a, motor_a, m15_a, h4_a, libro_a, v_a, cap_a, ahora = \
        _mundo_con_captura(tmp_path, "continua")
    res_a = D.verificar_y_reaccionar(D.BarreraCiclo(), cap_a, v_a, ahora, d_a,
                                     IDENT, motor_a, m15_a, h4_a, libro_a,
                                     commit=IDENT["commit"])
    assert res_a["igual"] is True
    continua = res_a["terminal"]
    assert continua["estado"] == C.COMPLETADO

    # (b) CAÍDA con la comparación `pending`: proceso nuevo, objetos nuevos
    d_b, motor_b, m15_b, h4_b, libro_b, _, _, _ = \
        _mundo_con_captura(tmp_path, "caida")
    m15r = {m: S.Almacen.cargar(m, "15m", a.ruta, requerido=True)
            for m, a in m15_b.items()}
    h4r = {m: S.Almacen.cargar(m, "4h", a.ruta, requerido=True)
           for m, a in h4_b.items()}
    libror = Ledger(libro_b.ruta, commit=IDENT["commit"])
    mr = Motor(m15r, h4r, MERCADOS, libror, bootstrap_hasta=1)
    barrera = D.BarreraCiclo()
    reanudado = D.reanudar(barrera, d_b, IDENT, mr, m15r, h4r, libror, ahora)

    # el arranque COMPLETÓ la comparación y publicó
    assert reanudado["reanudado"] is True
    assert reanudado["comparacion"]["igual"] is True
    assert reanudado["estado"] == continua["estado"] == C.COMPLETADO
    for campo in ("motivo", "evidencia", "heads", "firma",
                  "motivos_adicionales"):
        assert reanudado["cuerpo"][campo] == continua["cuerpo"][campo]
    assert not os.path.exists(os.path.join(d_b, C.ARCHIVO_SOLICITUD_TERMINAL))

    # y no ingirió: la reanudación no abre ciclos
    heads = {m: a.head for m, a in m15r.items()}
    parte = D.ciclo(fetch_reloj(ahora), barrera, mr, m15r, h4r, libror,
                    E.Verificacion.cargar(
                        os.path.join(d_b, C.ARCHIVO_VERIFICACION)),
                    lambda: ahora, estado_dir=d_b, identidad=IDENT)
    assert parte["ingirio"] is False
    assert {m: a.head for m, a in m15r.items()} == heads


def test_g40_la_captura_autorizada_liga_el_ok_a_SU_comparacion(tmp_path):
    """§13.4.1. Excluir el hash mutable del sidecar resuelve el choque con
    §9.1.3, pero solo: sin ligadura, `habilita_cierre()` —que mira estado y
    tiempos, no procedencia— dejaba que el `ok` de OTRA comparación habilitara
    un `COMPLETED` que nadie autorizó."""
    d, motor, m15, h4, libro, v, captura, ahora = \
        _mundo_con_captura(tmp_path, "ligadura")
    req = json.load(open(os.path.join(d, C.ARCHIVO_SOLICITUD_TERMINAL),
                         encoding="utf-8"))
    assert req["captura_autorizada"] == {
        "desde": ahora, "digest": captura["digest"],
        "firma": captura["firma"], "copia": captura["destino"]}

    # un `ok` de OTRA captura NO habilita
    v.conforme(ahora + 1, "digest-ajeno", "firma-ajena")
    with pytest.raises(ValueError, match="no deriva de la captura autorizada"):
        D.publicar_pendiente(D.BarreraCiclo(), d, ahora, motor, m15, h4, libro,
                             v, IDENT)
    assert not os.path.exists(os.path.join(d, C.ARCHIVO_COMPLETADO))

    # el `ok` de SU captura sí
    v.conforme(ahora + 2, captura["digest"], captura["firma"])
    hecho = D.publicar_pendiente(D.BarreraCiclo(), d, ahora, motor, m15, h4,
                                 libro, v, IDENT)
    assert hecho["estado"] == C.COMPLETADO


def test_g40_las_transiciones_desde_la_captura_son_dos_y_solo_dos(tmp_path):
    """§13.4.1: `pending → ok` y `pending → divergent`. Ninguna otra."""
    d, motor, m15, h4, libro, v, captura, ahora = \
        _mundo_con_captura(tmp_path, "transiciones")

    # `pending` de OTRA captura: la comparación en curso no es la autorizada
    v.pendiente(ahora + 1, "otro", "otra", str(tmp_path / "otra"))
    with pytest.raises(ValueError, match="no es la autorizada"):
        D.publicar_pendiente(D.BarreraCiclo(), d, ahora, motor, m15, h4, libro,
                             v, IDENT)

    # `deferred` no es transición autorizada desde una captura congelada
    v.diferir(ahora + 2, {"BTCUSDT_15m": 1})
    with pytest.raises(ValueError, match="transición no autorizada"):
        D.publicar_pendiente(D.BarreraCiclo(), d, ahora, motor, m15, h4, libro,
                             v, IDENT)

    # una divergencia contra OTRA captura tampoco
    v.divergente(ahora + 3, {"digest": "otro", "firma": "otra"},
                 {"digest": "x", "firma": "y"})
    with pytest.raises(ValueError, match="no es contra la captura autorizada"):
        D.publicar_pendiente(D.BarreraCiclo(), d, ahora, motor, m15, h4, libro,
                             v, IDENT)

    # la divergencia contra SU captura sí, y gana por precedencia
    v.divergente(ahora + 4,
                 {"digest": captura["digest"], "firma": captura["firma"]},
                 {"digest": "x", "firma": "y"})
    hecho = D.publicar_pendiente(D.BarreraCiclo(), d, ahora, motor, m15, h4,
                                 libro, v, IDENT)
    assert hecho["estado"] == C.BLOQUEADO
    assert hecho["cuerpo"]["motivo"] == C.MOTIVO_DIVERGENCIA


def test_g40bis_un_ciclo_que_esperaba_el_mutex_no_ingiere(tmp_path):
    """La carrera REAL: el ciclo pide la barrera, la fase A la tiene y marca
    `cierre_en_curso`, y recién ahí el ciclo entra.

    Comprobar la bandera solo ANTES del mutex no servía: el ciclo entraba y
    movía almacenes y libro DESPUÉS del estado que el request ya autorizó, y
    la publicación fallaba cerrado sobre una cohorte sana."""
    import threading
    motor, m15, h4, libro = mundo(tmp_path, n15=210)
    d = _estado_dir(tmp_path)
    sidecar_ok(d)
    v = E.Verificacion.cargar(os.path.join(d, C.ARCHIVO_VERIFICACION))
    ahora = ahora_de(m15, h4)
    barrera = D.BarreraCiclo()
    heads = {m: a.head for m, a in m15.items()}
    firma = libro.firma()

    entro = threading.Event()
    salio = threading.Event()
    parte = {}

    def correr_ciclo():
        entro.set()
        parte.update(D.ciclo(fetch_reloj(ahora), barrera, motor, m15, h4,
                             libro, v, lambda: ahora, estado_dir=d,
                             identidad=IDENT))
        salio.set()

    with barrera:                       # la fase A tiene el mutex
        hilo = threading.Thread(target=correr_ciclo)
        hilo.start()
        entro.wait(2)
        # el ciclo ya está bloqueado en `acquire`; ahora se marca el cierre
        D.registrar_causa(barrera, d, "muestra", IDENT, {"cierres": 50},
                          ahora, m15, h4, libro, ya_retenida=True,
                          verificacion=v)
        assert barrera.cierre_en_curso is True
    hilo.join(5)
    assert salio.is_set(), "el ciclo quedó colgado"

    # entró al mutex DESPUÉS de la marca, y no ingirió nada
    assert parte["ingirio"] is False
    assert "cierre en curso" in parte["motivo"]
    assert {m: a.head for m, a in m15.items()} == heads
    assert libro.firma() == firma

    # y por eso la publicación no falla cerrado sobre una cohorte sana
    hecho = D.publicar_pendiente(barrera, d, ahora, motor, m15, h4, libro, v,
                                 IDENT)
    assert hecho["estado"] == C.COMPLETADO
