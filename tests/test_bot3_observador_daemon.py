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
               "ultimo_t": alm.ultimo_t, "observacion_probatoria": False}]
    D._actualizar_silencio(s, partes, T0, h4)
    assert s.entradas[k]["estado"] == "activo"     # NO se resolvió

    # ahora sí llega
    alm.ofrecer([vela(falt)], "push")
    alm.drenar()
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
    E.solicitar_terminal(os.path.join(d, C.ARCHIVO_SOLICITUD_TERMINAL),
                         C.MOTIVO_SILENCIO, IDENT, {"h": 1}, 5, {"k": 1})
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
