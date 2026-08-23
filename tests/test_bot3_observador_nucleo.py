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

# SHA-256 hexadecimales canónicos: el sidecar valida FORMATO, no solo
# presencia (§13.4.2).
DIG, FIR = "a" * 64, "b" * 64
DIG_AJENO, FIR_AJENA = "c" * 64, "d" * 64

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
    v.conforme(100, DIG, FIR)
    assert v.habilita_cierre() is True
    v.diferir(200, {"BTCUSDT_15m": 2})
    assert v.habilita_cierre() is False
    v.pendiente(250, DIG, FIR)
    assert v.habilita_cierre() is False
    v.conforme(300, DIG, FIR)
    assert v.habilita_cierre() is True


def test_el_sidecar_de_verificacion_sobrevive_al_reinicio(tmp_path):
    """Sin él, un reinicio olvidaría la deferencia y el reporte tomaría por
    válida una verificación anterior."""
    ruta = str(tmp_path / "v.json")
    v = E.Verificacion(ruta)
    v.conforme(100, DIG, FIR)
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


def test_terminal_mas_request_residual_se_acredita_o_falla_cerrado(tmp_path):
    """§13.6: un terminal publicado con un `terminal.request` al lado NO es una
    contradicción — es el estado NORMAL de una caída entre publicar y borrar.

    Declararlo fallo cerrado exigía intervención humana en el caso más
    probable de todos. Lo que sí falla cerrado es un residual que NO deriva el
    terminal publicado."""
    ident = {"cohorte": "c", "contrato": "x", "commit": "y"}
    estado = {"heads": {}, "firma": "f", "sidecars": {}}

    # (a) COINCIDE: el ganador del residual deriva el terminal publicado
    d = str(tmp_path / "coincide")
    os.makedirs(d)
    req = E.solicitar_terminal(os.path.join(d, C.ARCHIVO_SOLICITUD_TERMINAL),
                               "muestra", ident, {"cierres": 50}, 1, estado)
    E.publicar_terminal(d, C.COMPLETADO, dict(ident, motivo="muestra"))
    leido = E.leer_terminal(d)                      # ya NO falla cerrado
    assert leido["estado"] == C.COMPLETADO
    assert leido["residual"] == req
    E.coincide_residual(req, leido["cuerpo"], ident, estado)

    # (b) DISCREPA en el ganador: el terminal no deriva del request
    d2 = str(tmp_path / "discrepa")
    os.makedirs(d2)
    req2 = E.solicitar_terminal(os.path.join(d2, C.ARCHIVO_SOLICITUD_TERMINAL),
                                C.MOTIVO_SILENCIO, ident, {}, 1, estado)
    E.publicar_terminal(d2, C.COMPLETADO, dict(ident, motivo="muestra"))
    with pytest.raises(ValueError, match="no deriva del ganador"):
        E.coincide_residual(req2, E.leer_terminal(d2)["cuerpo"], ident, estado)

    # (c) DISCREPA en el estado autorizado
    with pytest.raises(ValueError, match="autoriza otro estado"):
        E.coincide_residual(req, E.leer_terminal(d)["cuerpo"], ident,
                            {"heads": {"BTCUSDT_15m": 9}, "firma": "f",
                             "sidecars": {}})

    # (d) DISCREPA en la identidad
    with pytest.raises(ValueError, match="otra cohorte"):
        E.coincide_residual(req, E.leer_terminal(d)["cuerpo"],
                            dict(ident, cohorte="otra"), estado)


def test_el_registro_de_motivos_es_cerrado_y_falla_cerrado(tmp_path):
    """§13.2: un motivo que nadie definió no puede aportar un ganador. Antes
    caía en el default `COMPLETED` — un motivo mal escrito cerraba la cohorte
    como evaluable."""
    ruta = str(tmp_path / C.ARCHIVO_SOLICITUD_TERMINAL)
    ident = {"cohorte": "c", "contrato": "x", "commit": "y"}
    with pytest.raises(E.RequestInvalido, match="registro cerrado"):
        E.solicitar_terminal(ruta, "n_cierres", ident, {}, 1, {})
    assert not os.path.exists(ruta)
    # dos científicos a la vez: el motor corta UNA sola vez
    E.solicitar_terminal(ruta, "muestra", ident, {}, 1, {})
    with pytest.raises(E.RequestInvalido, match="dos motivos científicos"):
        E.solicitar_terminal(ruta, "tiempo", ident, {}, 2, {})
    # y la integridad SIEMPRE precede a lo científico
    cuerpo = E.solicitar_terminal(ruta, C.MOTIVO_SILENCIO, ident, {}, 3, {})
    assert cuerpo["motivo"] == C.MOTIVO_SILENCIO
    assert cuerpo["motivos_adicionales"] == ["muestra"]


def test_el_schema_del_request_no_tiene_migracion(tmp_path):
    """§13.7: el formato anterior nunca se desplegó, así que aceptarlo solo
    agregaría una ruta sin probar."""
    ruta = str(tmp_path / C.ARCHIVO_SOLICITUD_TERMINAL)
    ident = {"cohorte": "c", "contrato": "x", "commit": "y"}
    cuerpo = E.solicitar_terminal(ruta, "muestra", ident, {}, 1, {})
    assert cuerpo["schema_version"] == 2
    cuerpo["schema_version"] = 1
    cuerpo.pop("checksum")
    cuerpo["checksum"] = E.sha(E.canon(cuerpo))     # coherente: falla el SCHEMA
    E.escribir_atomico(ruta, E.canon(cuerpo))
    with pytest.raises(E.RequestInvalido, match="no hay migración"):
        E.leer_solicitud(ruta)


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


# ------------------------------------------- huella: sensibilidad completa
def test_la_huella_reacciona_a_TODOS_los_parametros_congelados(monkeypatch):
    """`PARAMS` incompleto dejaba cambiar estados, motivos, precedencia y
    estados de verificación sin mover `huella()`: comportamiento congelado que
    podía moverse sin que la identidad del observador lo reflejara."""
    base = C.huella()
    for nombre in C.PARAMS:
        actual = getattr(C, nombre)
        if isinstance(actual, str):
            nuevo = actual + "x"
        elif isinstance(actual, bool):
            nuevo = not actual
        elif isinstance(actual, int):
            nuevo = actual + 1
        elif isinstance(actual, tuple):
            nuevo = actual + ("x",)
        elif isinstance(actual, dict):
            nuevo = {**actual, "__x": 1}
        else:                                          # pragma: no cover
            raise AssertionError(f"{nombre}: tipo no contemplado")
        monkeypatch.setattr(C, nombre, nuevo)
        assert C.huella() != base, nombre
        monkeypatch.undo()
    assert C.huella() == base


def test_los_terminales_y_su_precedencia_entran_en_la_huella():
    """Explícito, porque fue el agujero concreto."""
    for nombre in ("COMPLETADO", "BLOQUEADO", "MOTIVO_SILENCIO",
                   "MOTIVO_DIVERGENCIA", "PRECEDENCIA_MOTIVOS", "VERIF_OK",
                   "VERIF_DIFERIDA", "VERIF_PENDIENTE", "VERIF_DIVERGENTE"):
        assert nombre in C.PARAMS, nombre


def test_el_competidor_rechazado_no_trunca_el_lock(tmp_path):
    """Abrir en `"w"` vaciaba el archivo ANTES de pedir el `flock`, así que un
    segundo observador rechazado borraba el PID del propietario."""
    ruta = str(tmp_path / "obs.lock")
    with E.Singleton(ruta):
        dueno = open(ruta, encoding="utf-8").read()
        assert dueno == str(os.getpid())
        for _ in range(3):
            with pytest.raises(E.SingletonTomado):
                with E.Singleton(ruta):
                    pass
            assert open(ruta, encoding="utf-8").read() == dueno


# --------------------------------------------------- silencio: ancla externa
class _AlmH4:
    """Almacén H4 mínimo con la API que usa el ancla."""

    def __init__(self, sellados):
        self._sellados = set(sellados)

    def cubre(self, t):
        return "vela" if t in self._sellados else "pendiente"


def test_el_almacen_desmiente_un_silencio_fabricado():
    """Ancla externa: declarar mudo un mercado cuyas velas SÍ están selladas
    exige además reescribir la cadena del almacén, que está anclada al
    snapshot autenticado por el commit."""
    s = _silencio()
    _observar(s, 3, cierre=1000)
    # el almacén tiene la vela que el silencio declara ausente
    with pytest.raises(S.SilencioDesmentido, match="TIENE la vela"):
        s.verificar_contra_almacen({"BTCUSDT": _AlmH4([999, 1000])})
    # y el `ultimo_cierre_valido` tiene que estar realmente sellado
    with pytest.raises(S.SilencioDesmentido, match="no está sellado"):
        s.verificar_contra_almacen({"BTCUSDT": _AlmH4([])})
    with pytest.raises(S.SilencioDesmentido, match="no hay almacén"):
        s.verificar_contra_almacen({})
    # caso legítimo: 999 sellado, 1000 ausente
    s.verificar_contra_almacen({"BTCUSDT": _AlmH4([999])})
    # una entrada resuelta ya no se contrasta
    s.resolver("BTCUSDT", "4h", 1000)
    s.verificar_contra_almacen({"BTCUSDT": _AlmH4([999, 1000])})


def test_el_modelo_de_amenaza_esta_declarado_y_no_promete_de_mas():
    """La garantía es detección de corrupción COHERENTE, no autenticación
    adversarial: un actor local que reescriba todo el documento de forma
    consistente produce uno aceptado, y eso está dicho."""
    fuente = open(S.__file__, encoding="utf-8").read()
    assert "MODELO DE AMENAZA" in fuente
    assert "detección de corrupción coherente" in fuente
    assert "NO garantizan es autenticación adversarial" in fuente

    # y la demostración: un atacante COHERENTE pasa. Se documenta como límite
    # conocido, no como falla del gate.
    s = _silencio()
    _observar(s, 4)
    doc = s.documento()
    k = S.clave("BTCUSDT", "4h", 1000)
    entrada = doc["entradas"][k]
    entrada["observaciones"].append(
        {"eligibility_time": BASE + 10 ** 7, "run_epoch": 1})
    entrada["cadena"] = S.cadena(entrada["observaciones"])
    entrada["evidencia_acumulada_ms"] = S.acumulado(entrada["observaciones"])
    doc.pop("doc_sha256")
    doc["doc_sha256"] = S._sha(S._canon(doc))
    import tempfile
    ruta = os.path.join(tempfile.mkdtemp(), "silencio.json")
    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    rehidratado = S.Silencio.cargar(ruta, COHORTE, "contrato-x", "commit-y")
    assert rehidratado.evidencia(k) > s.evidencia(k)   # LÍMITE CONOCIDO


def test_dos_primeros_arranques_simultaneos_no_dan_FileExistsError(tmp_path):
    """`exists()` + `open("x+")` era un TOCTOU: con el archivo AUSENTE, dos
    arranques a la vez hacían que el perdedor viera `FileExistsError` en vez
    de `SingletonTomado`, y un error inesperado no se maneja como «ya hay otro
    observador»."""
    import subprocess
    import sys
    ruta = str(tmp_path / "obs.lock")
    assert not os.path.exists(ruta)                # arranque en frío
    guion = (
        "import sys, time;"
        "sys.path.insert(0, %r);"
        "from modules.bot3.observador import estado as E;"
        "\ntry:\n"
        "    with E.Singleton(%r):\n"
        "        time.sleep(0.6)\n"
        "    print('GANO')\n"
        "except E.SingletonTomado:\n"
        "    print('TOMADO')\n"
        "except Exception as e:\n"
        "    print('INESPERADO:' + type(e).__name__)\n"
    ) % (str(ROOT), ruta)
    procesos = [subprocess.Popen([sys.executable, "-c", guion],
                                 stdout=subprocess.PIPE, text=True)
                for _ in range(6)]
    salidas = [p.communicate()[0].strip() for p in procesos]
    assert all(s in ("GANO", "TOMADO") for s in salidas), salidas
    assert salidas.count("GANO") == 1, salidas
    assert not any("INESPERADO" in s for s in salidas), salidas


# ---------- §13.4.2: vectores adversariales campo por campo ----------
def _sidecar(tmp_path, cuerpo, nombre="verificacion.json"):
    ruta = str(tmp_path / nombre)
    E.escribir_atomico(ruta, E.canon(
        dict({"schema_version": C.SCHEMA_VERIFICACION}, **cuerpo)))
    return ruta


def test_el_sidecar_valida_TIPOS_y_FORMATOS_no_solo_presencia(tmp_path):
    """Comprobar solo que el campo EXISTE era fail-open.

    Los tres primeros vectores son los que la auditoría reprodujo aceptados:
    `ok_bad_digest` llevaba `digest: null` y `firma: []` y aun así devolvía
    `habilita_cierre() is True`, habilitando el cierre científico sin que nada
    acreditara de qué comparación salía."""
    ok = {"instante": 10, "digest": DIG, "firma": FIR}
    pend = {"desde": 10, "digest": DIG, "firma": FIR, "copia": "/x"}
    div = {"esperado": {"digest": DIG, "firma": FIR},
           "obtenido": {"digest": DIG_AJENO, "firma": FIR_AJENA}}

    vectores = {
        # los tres reproducidos por la auditoría
        "ok_bad_digest": {"estado": C.VERIF_OK,
                          "ultima_ok": dict(ok, digest=None, firma=[])},
        "pending_bad_types": {"estado": C.VERIF_PENDIENTE,
                              "detalle": dict(pend, desde="10", digest=1)},
        "div_bad_shape": {"estado": C.VERIF_DIVERGENTE,
                          "detalle": {"esperado": "x", "obtenido": None}},
        # y el resto de los campos, uno por uno
        "ok_instante_bool": {"estado": C.VERIF_OK,
                             "ultima_ok": dict(ok, instante=True)},
        "ok_digest_corto": {"estado": C.VERIF_OK,
                            "ultima_ok": dict(ok, digest="a" * 63)},
        "ok_digest_mayuscula": {"estado": C.VERIF_OK,
                                "ultima_ok": dict(ok, digest="A" * 64)},
        "ok_firma_no_hex": {"estado": C.VERIF_OK,
                            "ultima_ok": dict(ok, firma="z" * 64)},
        "pending_copia_vacia": {"estado": C.VERIF_PENDIENTE,
                                "detalle": dict(pend, copia="   ")},
        "pending_copia_no_str": {"estado": C.VERIF_PENDIENTE,
                                 "detalle": dict(pend, copia=["/x"])},
        "pending_desde_bool": {"estado": C.VERIF_PENDIENTE,
                               "detalle": dict(pend, desde=False)},
        "div_esperado_sin_firma": {
            "estado": C.VERIF_DIVERGENTE,
            "detalle": dict(div, esperado={"digest": DIG})},
        "div_obtenido_basura": {
            "estado": C.VERIF_DIVERGENTE,
            "detalle": dict(div, obtenido={"digest": 1, "firma": None})},
        "deferencia_bool": {"estado": C.VERIF_DIFERIDA,
                            "ultima_deferencia": True,
                            "detalle": {"buffers_no_vacios": {"BTC_15m": 1}}},
        "deferred_buffers_no_objeto": {
            "estado": C.VERIF_DIFERIDA, "ultima_deferencia": 10,
            "detalle": {"buffers_no_vacios": ["BTC_15m"]}},
        "deferred_buffers_no_entero": {
            "estado": C.VERIF_DIFERIDA, "ultima_deferencia": 10,
            "detalle": {"buffers_no_vacios": {"BTC_15m": "2"}}},
        "deferred_buffers_cero": {
            "estado": C.VERIF_DIFERIDA, "ultima_deferencia": 10,
            "detalle": {"buffers_no_vacios": {"BTC_15m": 0}}},
        "ok_sin_ultima_ok": {"estado": C.VERIF_OK},
        "estado_desconocido": {"estado": "maybe", "ultima_ok": ok},
        "estado_ausente": {"ultima_ok": ok},
    }
    for nombre, cuerpo in vectores.items():
        ruta = _sidecar(tmp_path, cuerpo, f"{nombre}.json")
        with pytest.raises(E.VerificacionInvalida):
            E.Verificacion.cargar(ruta)

    # y los documentos BIEN formados sí cargan
    for cuerpo in ({"estado": C.VERIF_OK, "ultima_ok": ok},
                   {"estado": C.VERIF_PENDIENTE, "detalle": pend},
                   {"estado": C.VERIF_DIVERGENTE, "detalle": div},
                   {"estado": C.VERIF_DIFERIDA, "ultima_deferencia": 10,
                    "detalle": {"buffers_no_vacios": {"BTC_15m": 2}}}):
        v = E.Verificacion.cargar(_sidecar(tmp_path, cuerpo, "bueno.json"))
        assert v.estado == cuerpo["estado"]


def test_un_ok_malformado_no_habilita_el_cierre(tmp_path):
    """El vector exacto de la auditoría: `habilita_cierre=True` sobre un
    `ultima_ok` que no acreditaba nada."""
    ruta = _sidecar(tmp_path, {
        "estado": C.VERIF_OK,
        "ultima_ok": {"instante": 10, "digest": None, "firma": []}})
    with pytest.raises(E.VerificacionInvalida, match="SHA-256"):
        E.Verificacion.cargar(ruta)
