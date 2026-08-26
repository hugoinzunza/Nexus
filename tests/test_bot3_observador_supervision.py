"""Observador Bot3.v13 — gates de supervisión y procesos (§20.4, rev.34).

Cubre las partes de 48octies que necesitan procesos REALES: identidad de
nacimiento, handshake, los tres niveles de clausura, el barrido bajo lock y el
arbitraje con un diagnóstico previo.

No hay dobles de proceso: cada gate hace `fork`, mata de verdad y comprueba por
PID que no queda nada vivo ni zombi.

Las cuatro propiedades exigidas:

- nunca se señala por parecido: un PID reciclado no se barre;
- un segundo arranque con la corrida anterior SANA no barre nada;
- matar al wrapper NO reinicia: deja `supervisor_interrumpido` y bloquea;
- tras acreditar, el arranque siguiente arranca de verdad.
"""
import json
import os
import signal
import time

import pytest

from modules.bot3.observador import contrato as C
from modules.bot3.observador import diagnostico as G
from modules.bot3.observador import proceso as P
from modules.bot3.observador import supervision as S
from modules.bot3.observador.estado import canon, escribir_atomico
from modules.bot3.v9.contract import CONTRATO_HASH

IDENT = {"cohorte": "ensayo", "contrato": CONTRATO_HASH, "commit": "y" * 40}
AHORA = 1_700_000_000


def estado(tmp_path, nombre="estado"):
    d = str(tmp_path / nombre)
    os.makedirs(d, exist_ok=True)
    return d


def dormilon(segundos=30):
    """Hijo que se cuelga sin mirar su tubería: el caso que ninguna clausura
    cooperativa alcanza."""
    def arrancar():
        time.sleep(segundos)
        return 0
    return arrancar


def esperar_muerte(pid, plazo=5.0):
    fin = time.monotonic() + plazo
    while time.monotonic() < fin:
        if not P.vivo(pid):
            return True
        time.sleep(0.01)
    return False


# ==================== identidad de nacimiento (§20.4.3) ====================
def test_la_identidad_tiene_resolucion_de_MICROsegundos(tmp_path):
    """`ps -o lstart=` da SEGUNDOS: dos procesos nacidos en el mismo segundo
    son indistinguibles ahí, y un PID reciclado dentro de ese segundo pasaría
    la comprobación."""
    hijos = []
    for _ in range(2):
        pid = os.fork()
        if pid == 0:
            time.sleep(5)
            os._exit(0)
        hijos.append(pid)
    try:
        a, b = (P.identidad_de(p) for p in hijos)
        assert a["inicio"] != b["inicio"], "nacidos en el mismo microsegundo"
        assert a["inicio"] // 1_000_000 == b["inicio"] // 1_000_000, (
            "el gate exige que nazcan dentro del MISMO segundo")
        assert a["ejecutable"] == b["ejecutable"] == os.path.realpath(
            a["ejecutable"])
    finally:
        for p in hijos:
            os.kill(p, signal.SIGKILL)
            P.recolectar(p)


def test_un_PID_reciclado_NO_se_barre(tmp_path):
    """Se registra un árbol, se lo mata, y se finge que el mismo PID lo ocupa
    otro proceso. El barrido detecta la discrepancia y NO envía ninguna
    señal."""
    mio = P.identidad_de(os.getpid())
    # mismo PID, otro nacimiento: es lo que ve un PID reciclado
    for campo, valor in (("inicio", mio["inicio"] + 1),
                         ("ejecutable", "/usr/bin/otro"),
                         ("pgid", mio["pgid"] + 1)):
        with pytest.raises(P.ProcesoInvalido, match="NO es el registrado"):
            P.exigir_coincidencia(dict(mio, **{campo: valor}))

    # y un PID que ya no existe no es error: no hay nada que barrer
    pid = os.fork()
    if pid == 0:
        os._exit(0)
    P.recolectar(pid)
    assert P.exigir_coincidencia(
        {"pid": pid, "pgid": 1, "inicio": 1, "ejecutable": "/x"}) is False


def test_el_ejecutable_por_symlink_COINCIDE_tras_realpath(tmp_path):
    """Sin normalizar, el mismo binario vía symlink da rutas distintas y la
    comparación byte a byte daría un falso negativo que ABORTA el barrido —
    dejando vivo justo al proceso que había que matar."""
    real = P.ejecutable_de(os.getpid())
    enlace = str(tmp_path / "python-alias")
    os.symlink(real, enlace)
    assert os.path.realpath(enlace) == real
    assert P.ejecutable_de(os.getpid()) == os.path.realpath(enlace)


# ==================== handshake (§20.4.4) ====================
def test_el_daemon_no_toca_NADA_antes_de_que_el_sidecar_sea_durable(tmp_path):
    """El hijo hace `setpgid`, confirma y BLOQUEA. Publicar después dejaba una
    ventana en la que el daemon ya corría sin registro de su grupo — justo la
    que produce el huérfano que el nivel 3 debe barrer."""
    d = estado(tmp_path)
    testigo = str(tmp_path / "toco.txt")

    def arrancar():
        # si esto corriera antes de la publicación, el testigo existiría
        # cuando el sidecar todavía no
        with open(testigo, "w") as fh:
            fh.write("el daemon arrancó")
        time.sleep(5)
        return 0

    sup = S.lanzar_daemon(d, IDENT, arrancar, AHORA)
    try:
        assert sup["daemon"]["pgid"] == sup["daemon"]["pid"]   # grupo PROPIO
        assert sup["wrapper"]["pid"] == os.getpid()
        assert sup["wrapper"]["pgid"] != sup["daemon"]["pgid"], (
            "el wrapper debe quedar FUERA del grupo que va a barrer")
        # el sidecar ya es durable
        leido = S.leer_supervision(d)
        assert leido == sup
        # y el hijo recién ahora empieza a correr
        fin = time.monotonic() + 5
        while time.monotonic() < fin and not os.path.exists(testigo):
            time.sleep(0.01)
        assert os.path.exists(testigo)
    finally:
        os.kill(sup["daemon"]["pid"], signal.SIGKILL)
        P.recolectar(sup["daemon"]["pid"])


def test_un_hijo_que_no_confirma_es_matado_y_falla_cerrado(tmp_path):
    d = estado(tmp_path)
    vistos = []

    def arrancar():                                   # nunca llega a correr
        return 0

    original = S._leer_con_plazo
    S._leer_con_plazo = lambda fd, plazo: b""         # simula no-confirmación
    try:
        with pytest.raises(S.HandshakeFallido, match="no confirmó su grupo"):
            S.lanzar_daemon(d, IDENT, arrancar, AHORA,
                            cierre_cooperativo_s=0.2)
    finally:
        S._leer_con_plazo = original
    assert S.leer_supervision(d) is None              # nada quedó publicado


def test_si_falla_LIBERA_se_retira_el_sidecar(tmp_path):
    """El sidecar ya es durable y apunta a un daemon que nunca va a correr.
    Dejarlo haría que el wrapper siguiente registrara `supervisor_interrumpido`
    por una corrida que jamás existió."""
    d = estado(tmp_path)
    testigo = str(tmp_path / "no_debe_existir")

    def arrancar():
        with open(testigo, "w") as fh:
            fh.write("x")
        return 0

    real_write = os.write

    def write_roto(fd, datos):
        if datos == b"\x01":
            raise OSError(5, "EIO simulado")
        return real_write(fd, datos)

    os.write = write_roto
    try:
        with pytest.raises(S.HandshakeFallido, match="no se pudo liberar"):
            S.lanzar_daemon(d, IDENT, arrancar, AHORA)
    finally:
        os.write = real_write
    assert S.leer_supervision(d) is None
    assert not os.path.exists(testigo)                # el hijo nunca arrancó


# ==================== clausura nivel 1 (§20.4.1) ====================
def test_el_caso_normal_sale_por_EOF_sin_llegar_al_SIGKILL(tmp_path):
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(w)
        os.read(r, 1)                                 # espera el EOF
        os._exit(0)
    os.close(r)
    assert S.clausurar_hijo(pid, lambda: os.close(w), plazo_s=3) == "eof"
    assert not P.vivo(pid) and P.recolectar(pid, bloqueante=False) is None


def test_un_hijo_que_IGNORA_el_EOF_recibe_SIGKILL(tmp_path):
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(w)
        os.close(r)                                   # ni mira la tubería
        time.sleep(30)
        os._exit(0)
    os.close(r)
    assert S.clausurar_hijo(pid, lambda: os.close(w), plazo_s=0.3) == "sigkill"
    assert not P.vivo(pid)


# ==================== barrido: niveles 2 y 3 ====================
def test_un_trabajador_COLGADO_solo_lo_alcanza_el_killpg(tmp_path):
    """El caso duro: un trabajador detenido en DNS no mira su tubería y no ve
    ningún EOF, así que ninguna clausura cooperativa lo alcanza."""
    d = estado(tmp_path)
    listo = str(tmp_path / "nieto.pid")

    def arrancar():
        nieto = os.fork()
        if nieto == 0:
            time.sleep(60)                            # «colgado en DNS»
            os._exit(0)
        with open(listo, "w") as fh:
            fh.write(str(nieto))
        time.sleep(60)
        return 0

    sup = S.lanzar_daemon(d, IDENT, arrancar, AHORA)
    fin = time.monotonic() + 5
    while time.monotonic() < fin and not os.path.exists(listo):
        time.sleep(0.01)
    nieto = int(open(listo).read())
    assert P.vivo(nieto)
    assert os.getpgid(nieto) == sup["daemon"]["pgid"], "el nieto hereda el grupo"

    parte = S.barrer_grupo(sup)
    assert parte["señalado"] is True
    assert esperar_muerte(sup["daemon"]["pid"]) and esperar_muerte(nieto)
    P.recolectar(sup["daemon"]["pid"])
    # cero vivos y cero zombis, comprobado por PID
    assert not P.vivo(sup["daemon"]["pid"]) and not P.vivo(nieto)


def test_el_wrapper_no_se_mata_a_si_mismo_con_su_killpg(tmp_path):
    d = estado(tmp_path)
    sup = S.lanzar_daemon(d, IDENT, dormilon(), AHORA)
    S.barrer_grupo(sup)
    esperar_muerte(sup["daemon"]["pid"])
    P.recolectar(sup["daemon"]["pid"])
    assert P.vivo(os.getpid())                        # seguimos acá


def test_el_barrido_de_un_grupo_AJENO_falla_cerrado_sin_señal(tmp_path):
    d = estado(tmp_path)
    sup = S.lanzar_daemon(d, IDENT, dormilon(), AHORA)
    pid = sup["daemon"]["pid"]
    try:
        falso = dict(sup, daemon=dict(sup["daemon"],
                                      inicio=sup["daemon"]["inicio"] + 1))
        with pytest.raises(P.ProcesoInvalido, match="NO es el registrado"):
            S.barrer_grupo(falso)
        assert P.vivo(pid), "el proceso ajeno debe sobrevivir"
    finally:
        os.kill(pid, signal.SIGKILL)
        P.recolectar(pid)


# ==================== `supervisor.lock` (§20.4.2) ====================
def test_un_segundo_arranque_con_la_corrida_SANA_no_barre_nada(tmp_path):
    """El escenario que rev.29 rompía: un `pgid` vivo es exactamente lo que se
    ve cuando la corrida anterior está bien."""
    d = estado(tmp_path)
    lock = str(tmp_path / C.ARCHIVO_LOCK_SUPERVISOR)
    with S.Lock(lock):                                 # supervisor VIVO
        sup = S.lanzar_daemon(d, IDENT, dormilon(), AHORA)
        pid = sup["daemon"]["pid"]
        try:
            with pytest.raises(S.LockOcupado):
                with S.Lock(lock):
                    pytest.fail("el segundo NO debe entrar")
            assert P.vivo(pid), "el daemon sano sigue vivo"
            assert S.leer_supervision(d) == sup        # nada se tocó
        finally:
            os.kill(pid, signal.SIGKILL)
            P.recolectar(pid)


def test_una_salida_limpia_no_deja_sidecar_y_no_hay_barrido(tmp_path):
    d = estado(tmp_path)
    sup = S.lanzar_daemon(d, IDENT, dormilon(), AHORA)
    os.kill(sup["daemon"]["pid"], signal.SIGKILL)
    P.recolectar(sup["daemon"]["pid"])
    S.retirar_supervision(d)                           # salida ORDENADA
    parte = S.barrido_diferido(d, AHORA)
    assert parte["barrido"] is False
    assert G.leer_diagnostico(d) is None               # no se diagnostica nada


# ==================== §20.4.2.1 — matar al wrapper NO reinicia ============
def test_matar_al_wrapper_deja_supervisor_interrumpido_y_BLOQUEA(tmp_path):
    d = estado(tmp_path)
    sup = S.lanzar_daemon(d, IDENT, dormilon(), AHORA)
    pid = sup["daemon"]["pid"]
    # el wrapper muere sin clausurar: el sidecar QUEDA
    parte = S.barrido_diferido(d, AHORA)
    assert parte["barrido"] is True
    assert esperar_muerte(pid)
    P.recolectar(pid)

    diag = G.leer_diagnostico(d)
    assert diag["motivo"] == G.MOTIVO_SUPERVISOR and diag["codigo"] == 1
    assert diag["supervision_checksum"] == sup["checksum"]
    assert G.bloquea_arranque(d, IDENT) is diag or \
        G.bloquea_arranque(d, IDENT)["checksum"] == diag["checksum"]
    # el sidecar se CONSUMIÓ: si no, el próximo rediagnostica para siempre
    assert S.leer_supervision(d) is None


def test_el_ciclo_se_cierra_tras_ACREDITAR(tmp_path):
    """El deadlock de rev.31: sin retirar el sidecar, cada acreditación
    devolvía al mismo diagnóstico."""
    d = estado(tmp_path)
    sup = S.lanzar_daemon(d, IDENT, dormilon(), AHORA)
    S.barrido_diferido(d, AHORA)
    esperar_muerte(sup["daemon"]["pid"])
    P.recolectar(sup["daemon"]["pid"])

    diag = G.leer_diagnostico(d)
    assert G.bloquea_arranque(d, IDENT) is not None
    # ACREDITACIÓN humana
    G.publicar_acreditacion(d, IDENT, diag["checksum"], "hugo",
                            "revisé el libro y los almacenes", AHORA + 1)
    G.archivar_diagnostico(d, diag)
    # el arranque ya NO bloquea, y no hay nada que rediagnosticar
    assert G.bloquea_arranque(d, IDENT) is None
    assert S.barrido_diferido(d, AHORA + 2)["barrido"] is False


def test_una_caida_tras_diagnosticar_no_REdiagnostica(tmp_path):
    """§20.4.2.1: el `supervisor_interrumpido` CITA el sidecar que lo motivó,
    así que el wrapper siguiente distingue «ya diagnosticado, falta retirar»
    de «hay que diagnosticar»."""
    d = estado(tmp_path)
    sup = S.lanzar_daemon(d, IDENT, dormilon(), AHORA)
    pid = sup["daemon"]["pid"]
    # CAÍDA entre el paso 2 y el 3: se diagnostica y no se retira el sidecar
    S.barrer_grupo(sup)
    esperar_muerte(pid)
    P.recolectar(pid)
    S.arbitrar(d, sup, AHORA)
    primero = G.leer_diagnostico(d)
    assert S.leer_supervision(d) is not None           # el sidecar sigue

    parte = S.barrido_diferido(d, AHORA + 99)          # otro reloj
    assert parte["arbitraje"]["ya_diagnosticado"] is True
    assert G.leer_diagnostico(d) == primero            # NO se rediagnosticó
    assert S.leer_supervision(d) is None               # y ahora sí se retiró


# ==================== §20.4.2.2 — arbitraje ====================
def test_un_diagnostico_codigo_1_previo_se_CONSERVA(tmp_path):
    """Dice por qué murió el daemon, que es la causa raíz; la interrupción del
    supervisor es consecuencia."""
    d = estado(tmp_path)
    sup = S.lanzar_daemon(d, IDENT, dormilon(), AHORA)
    S.barrer_grupo(sup)
    esperar_muerte(sup["daemon"]["pid"])
    P.recolectar(sup["daemon"]["pid"])

    raiz = G.diagnostico(IDENT, G.MOTIVO_SENAL, 1, AHORA - 5, senal=9,
                         estado_crudo=137)
    G.publicar_diagnostico(d, raiz)
    parte = S.arbitrar(d, sup, AHORA)
    assert parte["clasificacion"] == G.CLAS_PRESERVADO
    assert G.leer_diagnostico(d) == raiz                # intacto
    inc = json.load(open(parte["incidencia"]))
    assert inc["clasificacion"] == G.CLAS_PRESERVADO
    assert inc["supervision_checksum"] == sup["checksum"]


def test_un_diagnostico_codigo_2_previo_se_ARCHIVA_y_escala(tmp_path):
    """La serie transitoria no se pierde, y la severidad no baja."""
    d = estado(tmp_path)
    sup = S.lanzar_daemon(d, IDENT, dormilon(), AHORA)
    S.barrer_grupo(sup)
    esperar_muerte(sup["daemon"]["pid"])
    P.recolectar(sup["daemon"]["pid"])

    transitorio = G.diagnostico(IDENT, G.MOTIVO_EXCEPCION, 2, AHORA - 5,
                                transitorios=2, excepcion="BlockingIOError")
    G.publicar_diagnostico(d, transitorio)
    parte = S.arbitrar(d, sup, AHORA)
    assert parte["archivado"] and os.path.exists(parte["archivado"])
    assert json.load(open(parte["archivado"])) == transitorio
    assert G.leer_diagnostico(d)["motivo"] == G.MOTIVO_SUPERVISOR
    assert G.leer_diagnostico(d)["codigo"] == 1


def test_un_diagnostico_CORRUPTO_o_AJENO_no_se_toca(tmp_path):
    d = estado(tmp_path)
    for nombre, escribir, clas in (
        ("corrupto", lambda r: escribir_atomico(r, '{"roto": '),
         G.CLAS_CORRUPTO),
        ("ajeno", lambda r: escribir_atomico(r, canon(G.diagnostico(
            dict(IDENT, cohorte="otra"), G.MOTIVO_WRAPPER, 1, AHORA))),
         G.CLAS_AJENA),
    ):
        sub = estado(tmp_path, nombre)
        sup = S.lanzar_daemon(sub, IDENT, dormilon(), AHORA)
        S.barrer_grupo(sup)
        esperar_muerte(sup["daemon"]["pid"])
        P.recolectar(sup["daemon"]["pid"])
        ruta = os.path.join(sub, C.ARCHIVO_FALLO_CERRADO)
        escribir(ruta)
        antes = open(ruta, "rb").read()
        parte = S.arbitrar(sub, sup, AHORA)
        assert parte["clasificacion"] == clas
        assert open(ruta, "rb").read() == antes, "el documento no se toca"
        inc = json.load(open(parte["incidencia"]))
        assert inc["cohorte"] == IDENT["cohorte"]      # identidad del SIDECAR
        assert inc["diagnostico_sha256"] == G.sha_de_bytes(ruta)


# ==================== el sidecar como artefacto ====================
def test_el_sidecar_de_supervision_se_valida_entero(tmp_path):
    d = estado(tmp_path)
    mio = P.identidad_de(os.getpid())
    bueno = S.publicar_supervision(d, IDENT, mio, dict(mio, pid=mio["pid"]),
                                   AHORA)
    assert S.leer_supervision(d) == bueno

    for nombre, roto in {
        "schema_ajeno": dict(bueno, schema_version=2),
        "campo_extra": dict(bueno, inventado=1),
        "daemon_sin_pgid": dict(bueno, daemon={k: v for k, v in
                                               bueno["daemon"].items()
                                               if k != "pgid"}),
        "pid_bool": dict(bueno, daemon=dict(bueno["daemon"], pid=True)),
        "pid_cero": dict(bueno, daemon=dict(bueno["daemon"], pid=0)),
        "ejecutable_relativo": dict(bueno, daemon=dict(bueno["daemon"],
                                                       ejecutable="python3")),
        "publicado_texto": dict(bueno, publicado_en="1"),
        "contrato_corto": dict(bueno, contrato="a" * 63),
        "trabajador_basura": dict(bueno, trabajador={"pid": 1}),
    }.items():
        cuerpo = S._sellar(roto)
        with pytest.raises(S.SupervisionInvalida):
            S.validar_supervision(cuerpo, nombre)

    # el checksum alterado se detecta aunque todo lo demás valide
    with pytest.raises(S.SupervisionInvalida, match="checksum"):
        S.validar_supervision(dict(bueno, publicado_en=AHORA + 1))


def test_el_trabajador_se_actualiza_en_cada_respawn(tmp_path):
    """Sin esto el sidecar apuntaría a la generación muerta y el barrido
    diferido dejaría vivo justamente al trabajador colgado."""
    d = estado(tmp_path)
    mio = P.identidad_de(os.getpid())
    S.publicar_supervision(d, IDENT, mio, mio, AHORA)
    assert S.leer_supervision(d)["trabajador"] is None
    for generacion in (1, 2):
        cuerpo = S.actualizar_trabajador(d, dict(mio, generacion=generacion))
        assert S.leer_supervision(d)["trabajador"]["generacion"] == generacion
        assert cuerpo["checksum"] == S.leer_supervision(d)["checksum"]
