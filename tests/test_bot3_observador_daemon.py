"""Observador Bot3.v13 — gates del ciclo, la barrera y los terminales.

Checkpoint 3 del bloque 2. Las cuatro propiedades que se exigen:

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
                                      T_CORTE, TF_MS)

DUR = TF_MS["15m"]
DUR4 = TF_MS["4h"]
BASE = 1_700_000_000_000 // DUR * DUR
BASE4 = BASE // DUR4 * DUR4
IDENT = {"cohorte": "ensayo", "contrato": "x" * 64, "commit": "y" * 40}


class _Estado:
    def __init__(self, m):
        self.mercado = m
        self.estado = "flat"
        self.degradado = False
        self.candidato = None
        self.orden = None
        self.posicion = None
        self.salida = None
        self.zonas_tocadas = set()


class _Motor:
    """Motor mínimo con la superficie que usa el daemon."""

    def __init__(self, mercados=("BTCUSDT",), cierres=0, pendientes=()):
        self.mercados = tuple(mercados)
        self.estados = {m: _Estado(m) for m in self.mercados}
        self.cortado = False
        self._frontera_cruzada = True
        self.bootstrap_hasta = 1
        self._epocas_anunciadas = set()
        self.lotes_finalizados = []
        self.cierres = [{"t": i} for i in range(cierres)]
        self._pendientes = list(pendientes)
        self.procesados = []
        self.ciclos = []

    def iniciar_ciclo(self, reloj):
        self.ciclos.append(reloj)

    def finalizar_ciclo(self):
        pass

    def cierres_pendientes(self):
        return list(self._pendientes)

    def procesar_lote(self, T):
        self.procesados.append(T)


class _Libro:
    def __init__(self, ruta=None, firma="f" * 64):
        self.ruta = ruta
        self._firma = firma
        self.sincronizados = 0

    def firma(self):
        return self._firma

    def sincronizar(self):
        self.sincronizados += 1


def almacen(mercado, tf, n, ruta=None):
    dur = TF_MS[tf]
    ancla = BASE if tf == "15m" else BASE4
    a = S.Almacen(mercado, tf, ruta=ruta)
    a.nacer_en(ancla)
    a.ofrecer([{"t": ancla + i * dur, "o": 1.5, "h": 2.5, "l": 0.5, "c": 2.0,
                "v": 1.0} for i in range(n)], "push")
    a.drenar()
    return a


def mundo(tmp_path=None, n15=20, n4=10):
    ruta = (lambda n: str(tmp_path / n)) if tmp_path else (lambda n: None)
    m15 = {"BTCUSDT": almacen("BTCUSDT", "15m", n15, ruta("BTCUSDT_15m.jsonl"))}
    h4 = {"BTCUSDT": almacen("BTCUSDT", "4h", n4, ruta("BTCUSDT_4h.jsonl"))}
    return m15, h4


def mundo_al_dia(tmp_path):
    """Las dos series terminan CONTEMPORÁNEAS: si vivieran en épocas
    distintas, el lag mediría otra cosa y el ciclo nunca procesaría."""
    ahora = BASE + 20 * DUR
    n4 = (ahora - BASE4) // DUR4 + 1
    m15, h4 = mundo(tmp_path, n15=20, n4=n4)
    return m15, h4, ahora


def fetch_ok(reloj):
    def fetch(url, params):
        if url == C.ENDPOINT_TIME:
            return {"serverTime": reloj}
        return []
    return fetch


# ------------------------------------------------------- 1. reloj y ciclo
def test_ningun_ciclo_ingiere_sin_reloj(tmp_path):
    """Sin `serverTime` no se ingiere NADA: ni se toca el almacén, ni se abre
    ciclo en el motor, ni se sincroniza el libro."""
    m15, h4 = mundo()
    motor, libro = _Motor(), _Libro()
    v = E.Verificacion(str(tmp_path / "v.json"))
    heads = {m: a.head for m, a in m15.items()}

    for reloj in (None, {}, {"serverTime": "x"}, RuntimeError("timeout")):
        def fetch(url, params, _r=reloj):
            if url == C.ENDPOINT_TIME:
                if isinstance(_r, Exception):
                    raise _r
                return _r
            raise AssertionError("no se puede pedir velas sin reloj")

        parte = D.ciclo(fetch, D.BarreraCiclo(), motor, m15, h4, libro, v,
                        lambda: BASE)
        assert parte["ingirio"] is False
        assert "sin reloj" in parte["motivo"]
    assert motor.ciclos == []                     # el motor nunca abrió ciclo
    assert libro.sincronizados == 0
    assert {m: a.head for m, a in m15.items()} == heads


def test_un_ciclo_usa_UN_solo_serverTime_end_to_end(tmp_path):
    """El reloj se muestrea una vez y ANTES de la barrera. El motor recibe el
    reloj LOCAL como `processed_at` (CF-34), no el de Binance."""
    m15, h4 = mundo(tmp_path)
    motor, libro = _Motor(), _Libro(str(tmp_path / "l.jsonl"))
    v = E.Verificacion(str(tmp_path / "v.json"))
    pedidos = []
    relojes = iter([BASE + 10 ** 6, BASE + 2 * 10 ** 6])

    def fetch(url, params):
        pedidos.append(url)
        if url == C.ENDPOINT_TIME:
            return {"serverTime": next(relojes)}
        return []

    parte = D.ciclo(fetch, D.BarreraCiclo(), motor, m15, h4, libro, v,
                    lambda: 424242)
    assert pedidos.count(C.ENDPOINT_TIME) == 1     # UNA sola muestra
    assert parte["eligibility_time"] == BASE + 10 ** 6
    assert motor.ciclos == [424242]                # processed_at = LOCAL


def test_la_deriva_del_reloj_local_queda_en_el_parte(tmp_path):
    m15, h4 = mundo(tmp_path)
    motor, libro = _Motor(), _Libro(str(tmp_path / "l.jsonl"))
    v = E.Verificacion(str(tmp_path / "v.json"))
    parte = D.ciclo(fetch_ok(BASE), D.BarreraCiclo(), motor, m15, h4, libro, v,
                    lambda: BASE + C.DERIVA_MAX_MS + 1)
    assert parte["incidencias"][0]["tipo"] == "deriva_de_reloj"


# ------------------------------------------------------ 2. zona de corte
def test_fuera_de_la_zona_se_procesa_aunque_la_verificacion_este_pendiente(
        tmp_path):
    motor = _Motor(cierres=0, pendientes=[BASE + DUR])
    v = E.Verificacion(str(tmp_path / "v.json"))
    v.pendiente(1, "d", "f")
    assert D.en_zona_de_corte(motor, BASE) is False
    permiso = D.puede_procesar_lote(motor, BASE, v)
    assert permiso["procesar"] is True


def test_dentro_de_la_zona_no_se_procesa_sin_verificacion_ok(tmp_path):
    """El motor emite `abierta_al_corte` y `orden_al_corte` DENTRO del corte:
    demorar `completed.json` no alcanzaba, había que impedir que llegara a
    cortar."""
    motor = _Motor(cierres=CORTE_N_CIERRES - 1)
    motor.estados["BTCUSDT"].posicion = {"P_in": 1}     # un cierre posible
    assert D.en_zona_de_corte(motor, BASE) is True
    v = E.Verificacion(str(tmp_path / "v.json"))

    for preparar in (lambda: v.pendiente(1, "d", "f"),
                     lambda: v.diferir(1, {"BTCUSDT_15m": 2}),
                     lambda: v.divergente(1, {}, {})):
        preparar()
        permiso = D.puede_procesar_lote(motor, BASE, v)
        assert permiso["procesar"] is False
        assert permiso["zona_de_corte"] is True
    # `ok` ANTERIOR a una deferencia tampoco habilita
    v.conforme(10, "d", "f")
    v.diferir(20, {"BTCUSDT_4h": 1})
    assert D.puede_procesar_lote(motor, BASE, v)["procesar"] is False
    v.conforme(30, "d", "f")
    assert D.puede_procesar_lote(motor, BASE, v)["procesar"] is True


def test_la_zona_de_corte_tambien_la_abre_el_tiempo(tmp_path):
    motor = _Motor(cierres=0)
    assert D.en_zona_de_corte(motor, T_CORTE - CORTE_ADMIN_GRACIA_MS - 1) is False
    assert D.en_zona_de_corte(motor, T_CORTE - CORTE_ADMIN_GRACIA_MS) is True
    assert D.en_zona_de_corte(motor, T_CORTE) is True


def test_la_cota_de_cierres_por_lote_es_conservadora(tmp_path):
    """`mercados_vivos` es la cota: con dos mercados vivos, la zona se abre
    dos cierres antes."""
    motor = _Motor(mercados=("BTCUSDT", "ETHUSDT"), cierres=CORTE_N_CIERRES - 2)
    assert D.mercados_vivos(motor) == 0
    assert D.en_zona_de_corte(motor, BASE) is False
    motor.estados["BTCUSDT"].orden = {"order_id": "a"}
    motor.estados["ETHUSDT"].posicion = {"P_in": 1}
    assert D.mercados_vivos(motor) == 2
    assert D.en_zona_de_corte(motor, BASE) is True


def test_el_ciclo_no_procesa_lotes_dentro_de_la_zona_sin_ok(tmp_path):
    """De punta a punta: el lote no llega al motor."""
    m15, h4, ahora = mundo_al_dia(tmp_path)
    motor = _Motor(cierres=CORTE_N_CIERRES - 1, pendientes=[ahora])
    motor.estados["BTCUSDT"].posicion = {"P_in": 1}
    libro = _Libro(str(tmp_path / "l.jsonl"))
    v = E.Verificacion(str(tmp_path / "v.json"))
    v.pendiente(1, "d", "f")
    parte = D.ciclo(fetch_ok(ahora), D.BarreraCiclo(), motor, m15, h4, libro,
                    v, lambda: ahora)
    assert parte["decision"]["procesar"] is True    # la ingesta sí avanzó
    assert parte["procesados"] == []                # pero el lote NO se procesó
    assert motor.procesados == []
    assert parte["bloqueado_por"]["zona_de_corte"] is True

    # y con la verificación `ok` posterior, el MISMO lote sí se procesa
    v.conforme(2, "d", "f")
    parte = D.ciclo(fetch_ok(ahora), D.BarreraCiclo(), motor, m15, h4, libro,
                    v, lambda: ahora)
    assert parte["procesados"] == [ahora]
    assert motor.procesados == [ahora]


# --------------------------------------------------- 3. barrera y captura
def test_la_captura_exige_la_barrera_RETENIDA_no_readquirida(tmp_path):
    """Con un mutex no reentrante, readquirirla sería un deadlock."""
    m15, h4 = mundo(tmp_path)
    motor, libro = _Motor(), _Libro(str(tmp_path / "l.jsonl"))
    v = E.Verificacion(str(tmp_path / "v.json"))
    barrera = D.BarreraCiclo()
    with pytest.raises(RuntimeError, match="RETENIDA"):
        D.capturar(barrera, motor, m15, h4, None, libro,
                   str(tmp_path / "scratch"), BASE, v)
    with barrera:
        captura = D.capturar(barrera, motor, m15, h4, None, libro,
                             str(tmp_path / "scratch"), BASE, v)
    assert captura and len(captura["digest"]) == 64


def test_una_barrera_con_buffers_llenos_no_se_certifica(tmp_path):
    """`_buffer` no es caché derivada: ante un hueco contiene las velas que
    determinan `prueba_local`, el `detected_at` y el rango del marcador."""
    m15, h4 = mundo(tmp_path)
    # una vela futura queda en buffer porque falta la intermedia
    m15["BTCUSDT"].ofrecer([{"t": BASE + 30 * DUR, "o": 1, "h": 2, "l": 0.5,
                             "c": 1.5, "v": 1}], "push")
    assert D.buffers_no_vacios(m15, h4) == {"BTCUSDT_15m": 1}
    motor, libro = _Motor(), _Libro(str(tmp_path / "l.jsonl"))
    v = E.Verificacion(str(tmp_path / "v.json"))
    barrera = D.BarreraCiclo()
    with barrera:
        assert D.capturar(barrera, motor, m15, h4, None, libro,
                          str(tmp_path / "scratch"), BASE, v) is None
    assert v.estado == C.VERIF_DIFERIDA
    assert v.habilita_cierre() is False
    assert not os.path.exists(str(tmp_path / "scratch"))


def test_vivo_contra_frio_igual_deja_ok_y_distinto_bloquea(tmp_path):
    m15, h4 = mundo(tmp_path)
    motor, libro = _Motor(), _Libro(str(tmp_path / "l.jsonl"))
    v = E.Verificacion(str(tmp_path / "v.json"))
    barrera = D.BarreraCiclo()
    with barrera:
        captura = D.capturar(barrera, motor, m15, h4, None, libro,
                             str(tmp_path / "scratch"), BASE, v)
    assert v.estado == C.VERIF_PENDIENTE
    assert v.habilita_cierre() is False            # pendiente NO habilita
    assert D.comparar_en_frio(captura, captura["digest"], captura["firma"],
                              v, BASE + 1) is True
    assert v.habilita_cierre() is True
    # y una divergencia deja la cohorte inhabilitada para siempre
    assert D.comparar_en_frio(captura, "0" * 64, captura["firma"], v,
                              BASE + 2) is False
    assert v.estado == C.VERIF_DIVERGENTE
    assert v.habilita_cierre() is False


def test_el_digest_de_la_captura_incluye_el_silencio(tmp_path):
    m15, h4 = mundo(tmp_path)
    motor, libro = _Motor(), _Libro(str(tmp_path / "l.jsonl"))
    barrera = D.BarreraCiclo()
    s = SIL.Silencio({"id": "e"}, "c", "k")
    s.abrir_corrida()
    s.observar("BTCUSDT", "4h", BASE4, BASE4 - DUR4, BASE)
    digests = []
    for doc in (None, s.documento()):
        v = E.Verificacion(str(tmp_path / f"v{len(digests)}.json"))
        with barrera:
            digests.append(D.capturar(
                barrera, motor, m15, h4, doc, libro,
                str(tmp_path / f"s{len(digests)}"), BASE, v)["digest"])
    assert digests[0] != digests[1]


# -------------------------------------------------------- 4. terminales
def test_ningun_terminal_parcial_se_publica(tmp_path):
    """Una caída entre la solicitud y la publicación se reanuda; nunca queda
    un terminal a medias que alguien lea como cerrado."""
    d = str(tmp_path)
    m15, h4 = mundo(tmp_path)
    motor, libro = _Motor(), _Libro(str(tmp_path / "l.jsonl"))
    ruta_req = os.path.join(d, C.ARCHIVO_SOLICITUD_TERMINAL)
    E.solicitar_terminal(ruta_req, C.MOTIVO_SILENCIO, IDENT, {"h": 1}, 5,
                         {"k": 1})
    # el arranque siguiente NO ingiere: reanuda
    leido = D.reanudar_si_hace_falta(d)
    assert leido["estado"] == "reanudar"
    assert not os.path.exists(os.path.join(d, C.ARCHIVO_BLOQUEADO))
    assert not os.path.exists(os.path.join(d, C.ARCHIVO_COMPLETADO))
    # y al completar la transición queda UN terminal y ningún request
    D.transicion_terminal(D.BarreraCiclo(), d, C.MOTIVO_SILENCIO, IDENT,
                          {"h": 1}, 9, motor, m15, h4, libro)
    assert not os.path.exists(ruta_req)
    final = D.reanudar_si_hace_falta(d)
    assert final["estado"] == C.BLOQUEADO
    assert final["cuerpo"]["motivo"] == C.MOTIVO_SILENCIO
    assert final["cuerpo"]["heads"]
    assert final["cuerpo"]["firma"] == libro.firma()


def test_blocked_integrity_no_ejecuta_el_cierre_cientifico(tmp_path):
    """No llama al corte del motor, no emite eventos terminales y no toca el
    libro: solo hace durable lo que ya existe y publica el marcador."""
    d = str(tmp_path)
    m15, h4 = mundo(tmp_path)
    motor, libro = _Motor(), _Libro(str(tmp_path / "l.jsonl"))
    motor.cortar = lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("BLOCKED_INTEGRITY no puede cortar el motor"))
    firma_antes = libro.firma()
    D.transicion_terminal(D.BarreraCiclo(), d, C.MOTIVO_DIVERGENCIA, IDENT,
                          {}, 9, motor, m15, h4, libro)
    assert motor.procesados == []
    assert motor.cortado is False
    assert libro.firma() == firma_antes
    cuerpo = json.load(open(os.path.join(d, C.ARCHIVO_BLOQUEADO),
                            encoding="utf-8"))
    assert cuerpo["estado"] == C.BLOQUEADO
    assert cuerpo["motivo"] == C.MOTIVO_DIVERGENCIA


def test_la_transicion_serializa_por_la_barrera(tmp_path):
    """Sin arbitraje, una implementación publicaría antes del ciclo siguiente
    y otra después: heads y firma distintos para la misma causa."""
    d = str(tmp_path)
    m15, h4 = mundo(tmp_path)
    motor, libro = _Motor(), _Libro(str(tmp_path / "l.jsonl"))
    barrera = D.BarreraCiclo()
    vista = []
    real = E.publicar_terminal

    def espia(estado_dir, estado, cuerpo):
        vista.append(barrera.retenida)
        return real(estado_dir, estado, cuerpo)

    import modules.bot3.observador.estado as mod
    original = mod.publicar_terminal
    mod.publicar_terminal = espia
    D.publicar_terminal = espia
    try:
        D.transicion_terminal(barrera, d, C.MOTIVO_SILENCIO, IDENT, {}, 9,
                              motor, m15, h4, libro)
    finally:
        mod.publicar_terminal = original
    assert vista == [True]                         # publicó DENTRO de la barrera
    assert barrera.retenida is False               # y la soltó al salir
