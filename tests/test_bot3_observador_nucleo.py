"""Observador Bot3.v13 — gates del núcleo (silencio, digest y terminales).

Diseño congelado rev.8, SHA-256
`660c25d6f9151dfcde5db06abf31158f58e5ad3d65a370897299d080561aa781`.

Este bloque NO toca red ni motor: son las piezas puras que deciden un terminal.
El ciclo y el cliente de Binance van aparte.

Nada de esto se despliega, actualiza snapshots ni inicia cohorte.
"""
import json
import os
import re

import pytest

from modules.bot3.observador import contrato as C
from modules.bot3.observador import estado as E
from modules.bot3.observador import silencio as S

BASE = 1_700_000_000_000
COHORTE = {"id": "ensayo"}


def _silencio():
    s = S.Silencio(COHORTE, "contrato-x", "commit-y")
    s.abrir_corrida()
    return s


def _observar(s, n, desde=BASE, paso=None, mercado="BTCUSDT", cierre=1000):
    paso = paso if paso is not None else C.CADENCIA_MS
    for i in range(n):
        s.observar(mercado, "4h", cierre, cierre - 1, desde + i * paso)
    return desde + (n - 1) * paso


# ---------------------------------------------------------------- contrato
def test_los_parametros_estan_congelados_y_tienen_huella():
    """Cambiar cualquiera es otro observador: la huella lo hace visible."""
    antes = C.huella()
    assert len(antes) == 64
    assert C.TF_OBSERVADAS == ("15m", "4h")       # H4 también, no solo M15
    assert len(C.UNIVERSO) == 7
    assert set(C.LAG_MAX_MS) == {"15m", "4h"}     # por TF, no uno solo
    assert C.TOPE_INTERVALO_MS == 2 * C.CADENCIA_MS
    assert "binance" in C.ENDPOINT_KLINES and "fapi" in C.ENDPOINT_KLINES
    assert C.huella() == antes


def test_el_observador_no_importa_nada_de_ejecucion():
    """API pública, sin credenciales: la falla máxima es no obtener datos."""
    raiz = os.path.dirname(C.__file__)
    for nombre in os.listdir(raiz):
        if not nombre.endswith(".py"):
            continue
        fuente = open(os.path.join(raiz, nombre), encoding="utf-8").read()
        for prohibido in ("BINANCE_TRADE", "api_key", "apiKey", "secret",
                          "signature", "/fapi/v1/order", "/fapi/v1/account"):
            assert prohibido not in fuente, f"{nombre}: {prohibido}"
        # ni el módulo `bot` (el que SÍ opera en vivo), ni testnet
        assert not re.search(r"\bmodules\.bot\b(?!3)", fuente), nombre
        assert "testnet" not in fuente.lower(), nombre


# ---------------------------------------------------------------- silencio
def test_la_primera_observacion_aporta_cero():
    s = _silencio()
    _observar(s, 1)
    assert s.evidencia(S.clave("BTCUSDT", "4h", 1000)) == 0
    _observar(s, 2)                               # dos más, contiguas
    assert s.evidencia(S.clave("BTCUSDT", "4h", 1000)) == C.CADENCIA_MS


def test_el_primer_intervalo_tras_reiniciar_aporta_cero():
    """rev.6 le daba `TOPE_INTERVALO`, y eso contaba como evidencia un tramo
    que nadie observó. Una corrida partida acumula estrictamente MENOS que la
    continua, nunca más."""
    continua = _silencio()
    _observar(continua, 6)
    partida = _silencio()
    _observar(partida, 3)
    partida.abrir_corrida()                       # reinicio
    _observar(partida, 3, desde=BASE + 3 * C.CADENCIA_MS)
    k = S.clave("BTCUSDT", "4h", 1000)
    assert continua.evidencia(k) == 5 * C.CADENCIA_MS
    assert partida.evidencia(k) == 4 * C.CADENCIA_MS
    assert partida.evidencia(k) < continua.evidencia(k)


def test_el_tiempo_apagado_no_acumula_nada():
    """80 h apagado y una paginación válida al volver NO bloquean: el
    comparador es evidencia acumulada, no una resta de relojes."""
    s = _silencio()
    _observar(s, 3)
    s.abrir_corrida()
    s.observar("BTCUSDT", "4h", 1000, 999, BASE + 80 * 3600 * 1000)
    k = S.clave("BTCUSDT", "4h", 1000)
    assert s.evidencia(k) == 2 * C.CADENCIA_MS    # solo lo observado
    assert s.ganadora() is None


def test_el_tope_acota_un_intervalo_largo_dentro_de_una_corrida():
    s = _silencio()
    s.observar("BTCUSDT", "4h", 1000, 999, BASE)
    s.observar("BTCUSDT", "4h", 1000, 999, BASE + 10 * 3600 * 1000)
    assert s.evidencia(S.clave("BTCUSDT", "4h", 1000)) == C.TOPE_INTERVALO_MS


def test_duplicado_y_retroceso_del_reloj_aportan_cero():
    s = _silencio()
    fin = _observar(s, 3)
    k = S.clave("BTCUSDT", "4h", 1000)
    antes = s.evidencia(k)
    s.observar("BTCUSDT", "4h", 1000, 999, fin)          # duplicado exacto
    s.observar("BTCUSDT", "4h", 1000, 999, fin - 5_000)  # regresivo
    assert s.evidencia(k) == antes
    assert len(s.entradas[k]["observaciones"]) == 3      # no mueve el puntero
    assert s.entradas[k]["regresiones"]                  # pero queda visible


def test_el_backfill_antes_del_umbral_resuelve_la_entrada():
    s = _silencio()
    _observar(s, 3)
    s.resolver("BTCUSDT", "4h", 1000)
    k = S.clave("BTCUSDT", "4h", 1000)
    assert s.entradas[k]["estado"] == "resuelto"         # se conserva
    s.observar("BTCUSDT", "4h", 1000, 999, BASE + 10 ** 9)
    assert len(s.entradas[k]["observaciones"]) == 3      # ya no gobierna
    # otro cierre faltante es OTRA clave, con su contador desde cero
    s.observar("BTCUSDT", "4h", 2000, 1999, BASE)
    assert s.evidencia(S.clave("BTCUSDT", "4h", 2000)) == 0


def test_varias_entradas_activas_y_ganadora_determinista():
    s = _silencio()
    n = C.SILENCIO_MAX_H4_MS // C.CADENCIA_MS + 2
    for mercado in ("ETHUSDT", "BTCUSDT"):            # orden de inserción ≠ total
        _observar(s, n, mercado=mercado)
    g = s.ganadora()
    assert g is not None
    # empate a la misma observación → gana el menor en el orden total
    assert g["mercado"] == "BTCUSDT"
    assert g["evidencia_acumulada_ms"] > C.SILENCIO_MAX_H4_MS
    assert g["observaciones"] == n
    assert len(g["cadena"]) == 64


def test_el_umbral_no_se_cruza_antes_de_tiempo():
    s = _silencio()
    _observar(s, C.SILENCIO_MAX_H4_MS // C.CADENCIA_MS)   # justo en el borde
    assert s.ganadora() is None


def test_el_tiempo_offline_queda_registrado_aunque_no_cuente():
    """Apagar el daemon congela el reloj del silencio. No se puede impedir
    por diseño; al menos se ve."""
    s = _silencio()
    _observar(s, 3)
    s.registrar_offline(80 * 3600 * 1000, BASE, BASE + 80 * 3600 * 1000)
    k = S.clave("BTCUSDT", "4h", 1000)
    assert s.entradas[k]["offline_ms"] == 80 * 3600 * 1000
    assert s.entradas[k]["offline_intervalos"]
    assert s.evidencia(k) == 2 * C.CADENCIA_MS            # no cambió


# --------------------------------------------------- silencio: persistencia
def test_el_sidecar_se_rehidrata_y_el_acumulado_se_deriva(tmp_path):
    s = _silencio()
    _observar(s, 4)
    s.abrir_corrida()
    _observar(s, 3, desde=BASE + 10 * C.CADENCIA_MS)
    ruta = str(tmp_path / "silencio.json")
    s.guardar(ruta)
    r = S.Silencio.cargar(ruta, COHORTE, "contrato-x", "commit-y")
    k = S.clave("BTCUSDT", "4h", 1000)
    assert r.evidencia(k) == s.evidencia(k)
    assert r.run_epoch == s.run_epoch
    # sin `run_epoch` persistido el acumulado no sería reconstruible
    assert all("run_epoch" in o for o in r.entradas[k]["observaciones"])


def test_el_sidecar_alterado_falla_cerrado(tmp_path):
    """Decide `BLOCKED_INTEGRITY`: no se acepta «otro digest válido»."""
    s = _silencio()
    _observar(s, 4)
    ruta = str(tmp_path / "silencio.json")
    s.guardar(ruta)
    k = S.clave("BTCUSDT", "4h", 1000)

    def con(mutar, patron):
        crudo = json.load(open(ruta, encoding="utf-8"))
        mutar(crudo)
        json.dump(crudo, open(ruta, "w", encoding="utf-8"))
        with pytest.raises(S.SilencioCorrupto, match=patron):
            S.Silencio.cargar(ruta, COHORTE, "contrato-x", "commit-y")
        s.guardar(ruta)                                   # restaura

    # campos que la CADENA de evidencia no cubre → los cubre `doc_sha256`
    con(lambda c: c["entradas"][k].update(offline_ms=9), "doc_sha256")
    con(lambda c: c["entradas"][k].update(estado="resuelto"), "doc_sha256")
    con(lambda c: c["entradas"][k].update(primer_cierre=7), "doc_sha256")
    con(lambda c: c.update(schema_version=99), "doc_sha256")
    con(lambda c: c.update(commit="ajeno"), "doc_sha256")


def test_el_sidecar_con_doc_sha_recalculado_igual_falla(tmp_path):
    """Un atacante que recalcula `doc_sha256` no gana: la cadena y el
    acumulado se derivan de las observaciones."""
    s = _silencio()
    _observar(s, 4)
    ruta = str(tmp_path / "silencio.json")
    s.guardar(ruta)
    k = S.clave("BTCUSDT", "4h", 1000)

    def con(mutar, patron):
        crudo = json.load(open(ruta, encoding="utf-8"))
        mutar(crudo)
        crudo.pop("doc_sha256")
        crudo["doc_sha256"] = S._sha(S._canon(crudo))     # rehecho a mano
        json.dump(crudo, open(ruta, "w", encoding="utf-8"))
        with pytest.raises(S.SilencioCorrupto, match=patron):
            S.Silencio.cargar(ruta, COHORTE, "contrato-x", "commit-y")
        s.guardar(ruta)

    con(lambda c: c["entradas"][k].update(evidencia_acumulada_ms=10 ** 12),
        "no se deriva")
    con(lambda c: c["entradas"][k]["observaciones"].append(
        {"eligibility_time": BASE + 10 ** 9, "run_epoch": 1}), "cadena")
    con(lambda c: c["entradas"][k].update(
        observaciones=list(reversed(c["entradas"][k]["observaciones"]))),
        "monótonas")
    con(lambda c: c["entradas"][k].update(cohorte=None) or c.update(
        cohorte={"id": "otra"}), "cohorte ajeno")


def test_la_misma_evidencia_reagrupada_da_los_mismos_bytes():
    """Invariante acotado a una continuidad: reagrupar las MISMAS
    observaciones en distinto número de llamadas da bytes idénticos."""
    a = _silencio()
    for i in range(6):
        a.observar("BTCUSDT", "4h", 1000, 999, BASE + i * C.CADENCIA_MS)
    b = _silencio()
    for tramo in ([0, 1], [2], [3, 4, 5]):
        for i in tramo:
            b.observar("BTCUSDT", "4h", 1000, 999, BASE + i * C.CADENCIA_MS)
    assert S._canon(a.documento()) == S._canon(b.documento())


# ------------------------------------------------------------------ digest
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
    def __init__(self):
        self.mercados = ("BTCUSDT",)
        self.estados = {"BTCUSDT": _Estado("BTCUSDT")}
        self.cortado = False
        self._frontera_cruzada = True
        self.bootstrap_hasta = 1
        self._epocas_anunciadas = set()
        self.lotes_finalizados = [1, 2, 3]
        self.cierres = [{"t": 1, "r": 1.5}, {"t": 2, "r": -1.0},
                        {"t": 3, "r": 0.4}]


class _Alm:
    def __init__(self, head, n):
        self.head = head
        self.registros = [None] * n


def _digest(motor=None, doc=None):
    motor = motor or _Motor()
    return E.observer_state_digest(
        motor, {"BTCUSDT": _Alm("a" * 64, 10)},
        {"BTCUSDT": _Alm("b" * 64, 5)}, doc)


def test_el_digest_cambia_con_un_cierre_INTERMEDIO():
    """Cardinalidad y último elemento dejaban pasar dos estados distintos con
    el mismo digest, y `cierres` participa del corte por semanas ISO."""
    base = _digest()
    m = _Motor()
    m.cierres[1] = {"t": 2, "r": -0.5}            # intermedio, misma longitud
    assert _digest(m) != base
    m2 = _Motor()
    m2.lotes_finalizados[1] = 99
    assert _digest(m2) != base


def test_el_digest_cambia_con_estado_vivo_que_el_libro_no_muestra():
    base = _digest()
    for mutar in (
        lambda m: setattr(m.estados["BTCUSDT"], "estado", "candidato_vivo"),
        lambda m: setattr(m.estados["BTCUSDT"], "degradado", True),
        lambda m: setattr(m.estados["BTCUSDT"], "candidato", {"id": "x"}),
        lambda m: setattr(m.estados["BTCUSDT"], "posicion", {"P_in": 1}),
        lambda m: m.estados["BTCUSDT"].zonas_tocadas.add(("z", 1)),
        lambda m: m._epocas_anunciadas.add(("BTCUSDT", 1)),
        lambda m: setattr(m, "cortado", True),
    ):
        m = _Motor()
        mutar(m)
        assert _digest(m) != base


def test_el_digest_incluye_el_estado_de_silencio():
    """El clon frío NO puede reconstruirlo: una ausencia H4 permanente todavía
    no es un marcador sellado. Sin esto, dos observadores con motor, almacenes
    y libro idénticos bloquearían en instantes distintos con el mismo digest."""
    s = _silencio()
    _observar(s, 3)
    otro = _silencio()
    _observar(otro, 4)
    assert _digest(doc=s.documento()) != _digest(doc=otro.documento())
    assert _digest(doc=None) != _digest(doc=s.documento())


def test_el_digest_ignora_los_derivados():
    m = _Motor()
    base = _digest(m)
    m._cache_h4 = {"BTCUSDT": ("x", {})}
    m._reloj_ciclo = 12345
    m._swm15 = {"BTCUSDT": []}
    assert _digest(m) == base


# ------------------------------------------------------------- terminales
def test_el_singleton_no_admite_dos_observadores(tmp_path):
    ruta = str(tmp_path / "obs.lock")
    with E.Singleton(ruta):
        with pytest.raises(E.SingletonTomado):
            with E.Singleton(ruta):
                pass
    with E.Singleton(ruta):                       # liberado al salir
        pass


def test_completed_exige_ok_posterior_a_toda_deferencia(tmp_path):
    v = E.Verificacion(str(tmp_path / "v.json"))
    assert v.habilita_cierre() is False           # sin verificación exitosa
    v.conforme(100, "d", "f")
    assert v.habilita_cierre() is True
    v.diferir(200, {"BTCUSDT_15m": 2})
    assert v.habilita_cierre() is False
    v.pendiente(250, "d", "f")
    assert v.habilita_cierre() is False
    v.conforme(300, "d", "f")
    assert v.habilita_cierre() is True


def test_el_sidecar_de_verificacion_sobrevive_al_reinicio(tmp_path):
    """Sin él, un reinicio olvidaría la deferencia y el reporte tomaría por
    válida una verificación anterior."""
    ruta = str(tmp_path / "v.json")
    v = E.Verificacion(ruta)
    v.conforme(100, "d", "f")
    v.diferir(200, {"BTCUSDT_4h": 1})
    r = E.Verificacion.cargar(ruta)
    assert r.estado == C.VERIF_DIFERIDA
    assert r.ultima_ok["instante"] == 100
    assert r.ultima_deferencia == 200
    assert r.habilita_cierre() is False


def test_la_solicitud_terminal_se_reanuda_y_valida(tmp_path):
    d = str(tmp_path)
    ruta = os.path.join(d, C.ARCHIVO_SOLICITUD_TERMINAL)
    ident = {"cohorte": "c", "contrato": "x", "commit": "y"}
    E.solicitar_terminal(ruta, C.MOTIVO_SILENCIO, ident, {"h": 1}, 5, {"k": 1})
    leido = E.leer_terminal(d)
    assert leido["estado"] == "reanudar"
    assert leido["cuerpo"]["motivo"] == C.MOTIVO_SILENCIO
    crudo = json.load(open(ruta, encoding="utf-8"))
    crudo["evidencia"] = {"h": 2}                 # checksum queda viejo
    json.dump(crudo, open(ruta, "w", encoding="utf-8"))
    with pytest.raises(ValueError, match="alterado"):
        E.leer_terminal(d)


def test_la_integridad_precede_a_la_liveness(tmp_path):
    """Dos motivos concurrentes: `determinism_divergence` gana, y no por orden
    de llegada sino por precedencia congelada."""
    ruta = str(tmp_path / C.ARCHIVO_SOLICITUD_TERMINAL)
    ident = {"cohorte": "c", "contrato": "x", "commit": "y"}
    E.solicitar_terminal(ruta, C.MOTIVO_SILENCIO, ident, {}, 1, {})
    cuerpo = E.solicitar_terminal(ruta, C.MOTIVO_DIVERGENCIA, ident, {}, 2, {})
    assert cuerpo["motivo"] == C.MOTIVO_DIVERGENCIA
    # y al revés: el que llega después NO desplaza al de mayor precedencia
    ruta2 = str(tmp_path / "otro.request")
    E.solicitar_terminal(ruta2, C.MOTIVO_DIVERGENCIA, ident, {}, 1, {})
    cuerpo2 = E.solicitar_terminal(ruta2, C.MOTIVO_SILENCIO, ident, {}, 2, {})
    assert cuerpo2["motivo"] == C.MOTIVO_DIVERGENCIA


def test_completed_y_request_a_la_vez_es_fallo_cerrado(tmp_path):
    d = str(tmp_path)
    ident = {"cohorte": "c", "contrato": "x", "commit": "y"}
    E.publicar_terminal(d, C.COMPLETADO, {"cohorte": "c"})
    assert E.leer_terminal(d)["estado"] == C.COMPLETADO
    E.solicitar_terminal(os.path.join(d, C.ARCHIVO_SOLICITUD_TERMINAL),
                         C.MOTIVO_DIVERGENCIA, ident, {}, 1, {})
    with pytest.raises(ValueError, match="intervención humana"):
        E.leer_terminal(d)


def test_blocked_manda_y_no_se_reactiva(tmp_path):
    d = str(tmp_path)
    ident = {"cohorte": "c", "contrato": "x", "commit": "y"}
    E.solicitar_terminal(os.path.join(d, C.ARCHIVO_SOLICITUD_TERMINAL),
                         C.MOTIVO_SILENCIO, ident, {}, 1, {})
    E.publicar_terminal(d, C.BLOQUEADO, {"cohorte": "c",
                                         "motivo": C.MOTIVO_SILENCIO})
    leido = E.leer_terminal(d)
    assert leido["estado"] == C.BLOQUEADO         # el request se ignora
    assert leido["cuerpo"]["motivo"] == C.MOTIVO_SILENCIO


def test_los_dos_terminales_a_la_vez_es_fallo_cerrado(tmp_path):
    d = str(tmp_path)
    E.publicar_terminal(d, C.COMPLETADO, {"cohorte": "c"})
    E.publicar_terminal(d, C.BLOQUEADO, {"cohorte": "c"})
    with pytest.raises(ValueError, match="a la vez"):
        E.leer_terminal(d)
