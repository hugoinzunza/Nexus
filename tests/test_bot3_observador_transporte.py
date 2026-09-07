"""Observador Bot3.v13 — gates del transporte aislado (§20.4, rev.34).

Cubre 48ter, 48quater, 48sexies y 48septies. Procesos y tuberías REALES: no
hay dobles del canal, y las respuestas grandes se transfieren de verdad.

Las cinco propiedades exigidas:

- el deadline acota una petición aunque el servidor gotee bytes para siempre;
- el I/O no bloquea al padre ni se abraza con el trabajador;
- toda corrupción del IPC falla cerrado y NO consume intento;
- solo el deadline y los seis errores de red consumen intento;
- tras un respawn no se lee ni un byte de la generación anterior.
"""
import errno
import os
import signal
import time

import pytest

from modules.bot3.observador import contrato as C
from modules.bot3.observador import proceso as P
from modules.bot3.observador import trabajador as W
from modules.bot3.observador import transporte as T


def canal_con(hacer, **kw):
    def servir(r, w):
        return W.servir(r, w, hacer=hacer)
    return T.Canal(servir, **kw)


def eco(status=200, cuerpo=None):
    return lambda url, p, ct, rt: (status, cuerpo if cuerpo is not None
                                   else {"eco": p})


# ==================== sobres (§20.4.1) ====================
def test_un_sobre_a_medio_escribir_es_DETECTABLE(tmp_path):
    """Con el enmarcado de §5, no es un JSON plausible."""
    crudo = T.enmarcar({"generacion": 1, "pedido": 1, "ok": True})
    assert T.desenmarcar(crudo)["pedido"] == 1

    for nombre, roto in {
        "sin_salto": crudo[:-1],
        "truncado": crudo[:len(crudo) // 2],
        "checksum_roto": crudo.replace(crudo.split(b"\t")[1], b"0" * 64, 1),
        "longitud_mentida": b"9\t" + crudo.split(b"\t", 1)[1],
        "cabecera_ilegible": b"no-es-un-numero\tx\t{}\n",
    }.items():
        with pytest.raises(T.TransporteCerrado):
            T.desenmarcar(roto)


def test_una_longitud_sobre_MAX_SOBRE_no_reserva_memoria(tmp_path):
    """El techo existe para no reservar memoria según un campo de longitud que
    ya no es confiable."""
    enorme = f"{C.MAX_SOBRE + 1}\t{'a' * 64}\t{{}}\n".encode()
    with pytest.raises(T.TransporteCerrado, match="techo"):
        T.desenmarcar(enorme)


def test_status_y_retry_after_viajan_como_campos_del_sobre(tmp_path):
    """El cuerpo solo no permite distinguir un `429` de un `200`, y el backoff
    decide con los dos."""
    def fallar_429(url, p, ct, rt):
        import urllib.error
        import email.message
        cab = email.message.Message()
        cab["Retry-After"] = "7"
        raise urllib.error.HTTPError(url, 429, "slow down", cab, None)

    c = canal_con(fallar_429)
    try:
        with pytest.raises(T.FalloDeRed) as exc:
            c.pedir("https://x/k", {})
        assert exc.value.clase == T.ERR_429
        assert exc.value.retry_after == "7"
    finally:
        c.cerrar(plazo_s=2)


# ==================== correlación estricta (§20.4.1) ====================
def test_una_respuesta_con_ID_AJENO_falla_cerrado(tmp_path):
    """Con UNA petición en vuelo y canal nuevo por generación, un ID que no
    coincide es IMPOSIBLE en operación válida: solo puede venir de un protocolo
    corrupto. Descartarlo lo convertía en una espera que terminaba venciendo el
    deadline —que sí es reintentable—, así que una corrupción del observador se
    habría reintentado cinco veces y seguido."""
    base = {"generacion": 1, "pedido": 1, "ok": True, "status": 200,
            "retry_after": None, "body": {}, "error": None}
    assert T.validar_respuesta(dict(base), 1, 1)
    for ajeno in (dict(base, pedido=2), dict(base, generacion=2)):
        with pytest.raises(T.TransporteCerrado, match="respuesta ajena"):
            T.validar_respuesta(ajeno, 1, 1)
    # TIPOS estrictos antes de correlacionar: `True == 1`, así que un
    # `generacion: true` correlacionaba con la generación 1
    for tipado in (dict(base, pedido="1"), dict(base, generacion=True),
                   dict(base, pedido=True), dict(base, generacion=1.0)):
        with pytest.raises(T.TransporteCerrado, match="no es entero"):
            T.validar_respuesta(tipado, 1, 1)


def test_el_schema_de_la_respuesta_es_cerrado(tmp_path):
    base = {"generacion": 1, "pedido": 1, "ok": True, "status": 200,
            "retry_after": None, "body": {}, "error": None}
    for nombre, roto in {
        "campo_extra": dict(base, inventado=1),
        "campo_ausente": {k: v for k, v in base.items() if k != "status"},
        "ok_con_error": dict(base, error=T.ERR_DNS),
        "status_no_entero": dict(base, status="200"),
        "error_desconocido": dict(base, ok=False, error="lo_que_sea"),
        # `ok` tiene que ser BOOLEANO: con `"false"` la cadena es verdadera en
        # Python y `pedir()` devolvía éxito sobre una respuesta que declaraba
        # un error
        "ok_cadena_false": dict(base, ok="false", error=T.ERR_DNS),
        "ok_cadena_true": dict(base, ok="true"),
        "ok_entero": dict(base, ok=1),
        # COHERENCIA entre campos: un `ok` con 503 se contradice a sí mismo
        "ok_con_5xx": dict(base, status=503),
        "ok_con_4xx": dict(base, status=404),
        "ok_con_retry_after": dict(base, retry_after="7"),
        "error_con_body": dict(base, ok=False, error=T.ERR_DNS,
                               body={"algo": 1}),
    }.items():
        with pytest.raises(T.TransporteCerrado):
            T.validar_respuesta(roto, 1, 1)


# ==================== deadline (§20.4) ====================
def test_un_servidor_que_GOTEA_bytes_no_sostiene_la_peticion(tmp_path):
    """El caso que `READ_TIMEOUT` no detecta: entrega actividad periódica y la
    petición viviría indefinidamente."""
    def goteo(url, p, ct, rt):
        while True:
            time.sleep(0.05)                    # actividad, sin terminar nunca

    c = canal_con(goteo, deadline_ms=400)
    try:
        t0 = time.monotonic()
        with pytest.raises(T.DeadlineVencido):
            c.pedir("https://x/k", {})
        assert time.monotonic() - t0 < 5, "el deadline no acotó la petición"
        assert c.trabajador is None, "se respawnea tras el deadline"
    finally:
        c.cerrar(plazo_s=2)


def test_una_resolucion_DNS_bloqueada_se_corta_igual(tmp_path):
    """El socket todavía no existe y `getaddrinfo` no es cancelable desde el
    proceso que la llamó: solo matar al trabajador acota esto."""
    def dns_colgado(url, p, ct, rt):
        time.sleep(3600)

    c = canal_con(dns_colgado, deadline_ms=400)
    try:
        pid_antes = c.asegurar().pid
        with pytest.raises(T.DeadlineVencido):
            c.pedir("https://x/k", {})
        assert not P.vivo(pid_antes), "el trabajador colgado debe morir"
    finally:
        c.cerrar(plazo_s=2)


def test_una_respuesta_MAYOR_que_el_buffer_de_la_tuberia_llega_entera(tmp_path):
    """El abrazo mortal: sin drenar mientras el trabajador escribe, los dos
    quedan detenidos y el deadline termina matando una respuesta VÁLIDA."""
    grande = {"velas": ["x" * 512 for _ in range(2000)]}     # ~1 MB
    c = canal_con(eco(200, grande), deadline_ms=15_000)
    try:
        r = c.pedir("https://x/k", {})
        assert r["ok"] and len(r["body"]["velas"]) == 2000
    finally:
        c.cerrar(plazo_s=2)


def test_la_trama_completa_JUSTO_en_el_borde_se_acepta(tmp_path):
    """`monotonic()` se muestrea DESPUÉS de la trama completa: mirarlo antes
    del último `read` haría que una trama completa pareciera tardía."""
    r, w = os.pipe()
    T._no_bloqueante(r)
    sobre = T.enmarcar({"generacion": 1, "pedido": 1, "ok": True,
                        "status": 200, "retry_after": None, "body": {},
                        "error": None})
    os.write(w, sobre)
    try:
        # deadline holgado: llega completa y se acepta
        assert T.leer_sobre(r, time.monotonic() + 2) == sobre
        # y una INCOMPLETA al vencer, no
        os.write(w, sobre[:10])
        with pytest.raises(T.DeadlineVencido):
            T.leer_sobre(r, time.monotonic() + 0.2)
    finally:
        os.close(r)
        os.close(w)


def test_pedir_usa_UN_SOLO_deadline_para_despacho_y_respuesta(tmp_path):
    """El deadline arranca ANTES del primer byte y cubre las dos mitades.

    Calcularlo de nuevo antes de leer daría al padre `2 × REQUEST_DEADLINE` en
    el peor caso, que es justo lo que la cota quiere impedir: el gate compara
    el valor que recibe `escribir_todo` con el que recibe `leer_sobre` y exige
    que sea el MISMO objeto de tiempo, no uno recalculado."""
    vistos = []
    real_escribir, real_leer = T.escribir_todo, T.leer_sobre

    def espia_escribir(fd, datos, deadline):
        vistos.append(("escribir", deadline))
        time.sleep(0.15)                     # el despacho CONSUME deadline
        return real_escribir(fd, datos, deadline)

    def espia_leer(fd, deadline):
        vistos.append(("leer", deadline))
        return real_leer(fd, deadline)

    T.escribir_todo, T.leer_sobre = espia_escribir, espia_leer
    c = canal_con(eco(), deadline_ms=5_000)
    try:
        c.pedir("https://x/k", {})
        assert [q for q, _ in vistos] == ["escribir", "leer"]
        assert vistos[0][1] == vistos[1][1], (
            "el deadline se recalculó entre despacho y respuesta")
    finally:
        T.escribir_todo, T.leer_sobre = real_escribir, real_leer
        c.cerrar(plazo_s=2)


def test_una_trama_COMPLETA_pero_TARDIA_se_rechaza(tmp_path):
    """El veredicto del borde se resuelve con el reloj muestreado DESPUÉS de la
    trama completa. Sin esa comprobación, una respuesta que llega entera fuera
    de plazo pasaba como válida y la cota dejaba de ser cota.

    El reloj se INYECTA porque el caso es una carrera de microsegundos: con el
    reloj real, la comprobación de arriba del bucle se dispara primero y el
    gate pasaría sin haber ejercido nunca la del borde — que es exactamente
    cómo la versión anterior de este gate sobrevivía a la mutación."""
    r, w = os.pipe()
    T._no_bloqueante(r)
    sobre = T.enmarcar({"generacion": 1, "pedido": 1, "ok": True,
                        "status": 200, "retry_after": None, "body": {},
                        "error": None})
    os.write(w, sobre)
    deadline = 100.0
    # el bucle entra con plazo (99.0), la trama llega COMPLETA, y recién al
    # muestrear después de leerla el reloj ya pasó el plazo (100.5)
    marcas = iter([99.0, 100.5, 100.5, 100.5])
    try:
        with pytest.raises(T.DeadlineVencido, match="fuera de plazo"):
            T.leer_sobre(r, deadline, reloj=lambda: next(marcas))
        # y con el reloj DENTRO del plazo, la misma trama se acepta
        os.write(w, sobre)
        dentro = iter([99.0, 99.5, 99.5])
        assert T.leer_sobre(r, deadline, reloj=lambda: next(dentro)) == sobre
    finally:
        os.close(r)
        os.close(w)


def test_el_deadline_arranca_ANTES_del_primer_byte(tmp_path):
    """Escribir en una tubería BLOQUEA cuando el buffer del kernel se llena:
    arrancarlo después dejaba al padre detenido con el reloj parado."""
    r, w = os.pipe()
    T._no_bloqueante(w)
    try:
        # se llena el buffer sin que nadie lea
        relleno = b"x" * 65536
        try:
            while True:
                os.write(w, relleno)
        except OSError as exc:
            assert exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK)
        t0 = time.monotonic()
        with pytest.raises(T.DeadlineVencido, match="escribiendo el pedido"):
            T.escribir_todo(w, relleno, time.monotonic() + 0.3)
        assert time.monotonic() - t0 < 3
    finally:
        os.close(r)
        os.close(w)


# ==================== muerte del trabajador ====================
def test_una_muerte_ESPONTANEA_falla_cerrado_y_no_consume_intento(tmp_path):
    """Un proceso que se cae solo no es una falla de red sino del observador.
    Tratarla como transitoria la haría reintentar cinco veces y seguir como si
    nada."""
    def suicida(url, p, ct, rt):
        os._exit(3)                                  # muere sin contestar

    c = canal_con(suicida, deadline_ms=5_000)
    try:
        with pytest.raises(T.TransporteCerrado, match="EOF con la trama"):
            c.pedir("https://x/k", {})
    finally:
        c.cerrar(plazo_s=2)


def test_tras_un_RESPAWN_no_se_lee_ni_un_byte_de_la_generacion_anterior(
        tmp_path):
    """Reusar la tubería habría dejado media respuesta de la generación
    anterior esperando al principio del flujo.

    El marcador vive en DISCO, no en una closure: el `fork` copia la memoria,
    así que un contador en el padre nunca ve lo que hizo el hijo."""
    marca = str(tmp_path / "ya_colgo")

    def hacer(url, p, ct, rt):
        if not os.path.exists(marca):
            # la PRIMERA generación escribe basura en su tubería y se cuelga:
            # el padre la mata por deadline con media respuesta en el canal
            with open(marca, "w") as fh:
                fh.write("x")
            os.write(2, b"")
            time.sleep(3600)
        return (200, {"generacion_nueva": True})

    c = canal_con(hacer, deadline_ms=400)
    try:
        g1 = c.asegurar().generacion
        pid1 = c.trabajador.pid
        with pytest.raises(T.DeadlineVencido):
            c.pedir("https://x/k", {})
        assert not P.vivo(pid1)
        # el canal nuevo es OTRO, y el pedido vuelve a numerar desde 1
        r = c.pedir("https://x/k", {})
        assert c.generacion == g1 + 1 and c.trabajador.pid != pid1
        assert r["generacion"] == c.generacion and r["pedido"] == 1
        assert r["body"] == {"generacion_nueva": True}
    finally:
        c.cerrar(plazo_s=2)


def test_el_trabajador_cierra_los_descriptores_AJENOS(tmp_path):
    """Sin esto se lleva copias del `supervisor.lock`, de los almacenes y del
    libro: sostendría locks que no son suyos."""
    from modules.bot3.observador import supervision as S
    lock = str(tmp_path / C.ARCHIVO_LOCK_SUPERVISOR)
    with S.Lock(lock):
        c = canal_con(eco())
        try:
            r = c.pedir("https://x/k", {"a": 1})
            assert r["ok"]
            pid = c.trabajador.pid
        finally:
            c.cerrar(plazo_s=2)
    # el lock del padre ya se soltó; si el trabajador lo hubiera heredado y
    # siguiera vivo, esto fallaría
    with S.Lock(lock):
        pass
    assert not P.vivo(pid)


# ==================== enum de errores (§20.4, gate 48sexies) ============
def test_cada_error_del_enum_hace_lo_que_declara(tmp_path):
    import urllib.error
    import socket
    import ssl

    casos = {
        T.ERR_DNS: socket.gaierror(8, "nodename nor servname provided"),
        T.ERR_CONEXION: ConnectionRefusedError(61, "Connection refused"),
        T.ERR_TLS: ssl.SSLError(1, "handshake failure"),
        T.ERR_LECTURA: socket.timeout("timed out"),
    }
    for clase, exc in casos.items():
        assert W.clasificar(exc)[0] == clase, clase

    for status, clase in ((429, T.ERR_429), (500, T.ERR_5XX),
                          (503, T.ERR_5XX), (400, T.ERR_4XX),
                          (403, T.ERR_4XX), (418, T.ERR_4XX)):
        err = urllib.error.HTTPError("u", status, "m", None, None)
        assert W.clasificar(err)[0] == clase, status

    # una excepción NUESTRA es `interno`, no de red
    assert W.clasificar(KeyError("bug"))[0] == T.ERR_INTERNO


def test_los_4xx_y_el_interno_NO_se_reintentan(tmp_path):
    """Los parámetros están congelados (§15): un `400` significa que el
    contrato del exchange cambió y un `403`/`418` que estamos bloqueados.
    Reintentar un baneo lo empeora."""
    import urllib.error
    for status in (400, 403, 418):
        def fallar(url, p, ct, rt, _s=status):
            raise urllib.error.HTTPError(url, _s, "no", None, None)

        c = canal_con(fallar)
        try:
            with pytest.raises(T.TransporteCerrado, match="no se reintenta"):
                c.pedir("https://x/k", {})
        finally:
            c.cerrar(plazo_s=2)


# ==================== backoff (gate 49) ====================
def test_solo_se_duerme_tras_los_fallos_1_a_4(tmp_path):
    """El quinto levanta de inmediato: dormir tras el último sería retrasar el
    fracaso sin cambiarlo, y la espera se la comería el `ExitTimeOut`."""
    dormidas = []
    intentos = {"n": 0}

    def siempre_falla():
        intentos["n"] += 1
        raise T.FalloDeRed(T.ERR_CONEXION)

    with pytest.raises(T.FalloDeRed):
        T.con_reintentos(siempre_falla, dormir=dormidas.append,
                         azar=lambda a, b: b)
    assert intentos["n"] == C.BACKOFF_INTENTOS
    assert len(dormidas) == C.BACKOFF_INTENTOS - 1, dormidas


def test_la_formula_del_backoff_esta_congelada(tmp_path):
    """`min(BACKOFF_MAX, BASE * 2**(n-1))`, con full jitter."""
    techos = [T.espera_de(n, azar=lambda a, b: b) for n in range(1, 6)]
    esperados = [min(C.BACKOFF_MAX_MS, C.BACKOFF_BASE_MS * 2 ** (n - 1)) / 1000
                 for n in range(1, 6)]
    assert techos == esperados
    # el jitter es COMPLETO: el piso es cero
    assert T.espera_de(3, azar=lambda a, b: a) == 0.0


def test_retry_after_se_acota_consume_intento_y_lo_malformado_se_ignora(
        tmp_path):
    """Sin la cota, un `Retry-After` hostil dormiría el ciclo por horas."""
    tope = C.BACKOFF_MAX_MS / 1000.0
    assert T.espera_de(1, retry_after=999_999) == tope
    assert T.espera_de(1, retry_after=1.5) == 1.5
    assert T.espera_de(1, retry_after=-5) == 0.0

    # segundos y HTTP-date
    assert T.interpretar_retry_after("7") == 7.0
    futuro = T.interpretar_retry_after("Wed, 21 Oct 2099 07:28:00 GMT")
    assert futuro and futuro > 0
    # una cabecera ROTA se ignora y se usa el jitter
    for basura in ("mañana", "", "  ", None, [], {"a": 1}, True):
        assert T.interpretar_retry_after(basura) is None

    # y consume intento igual
    intentos = {"n": 0}

    def con_429():
        intentos["n"] += 1
        raise T.FalloDeRed(T.ERR_429, retry_after="1")

    with pytest.raises(T.FalloDeRed):
        T.con_reintentos(con_429, dormir=lambda s: None)
    assert intentos["n"] == C.BACKOFF_INTENTOS


def test_el_sueno_del_backoff_es_INTERRUMPIBLE(tmp_path):
    """Un `SIGTERM` durante la última espera costaba `BACKOFF_MAX` completo."""
    sueno = T.SuenoInterrumpible()
    sueno.parar.set()
    t0 = time.monotonic()
    with pytest.raises(T.TransporteCerrado, match="apagado"):
        sueno(C.BACKOFF_MAX_MS / 1000.0)
    assert time.monotonic() - t0 < 1


def test_una_corrupcion_del_IPC_no_consume_intento(tmp_path):
    """Solo `FalloDeRed` entra al backoff. `TransporteCerrado` atraviesa
    `con_reintentos` sin reintentar: el observador está roto, no la red."""
    intentos = {"n": 0}

    def corrupto():
        intentos["n"] += 1
        raise T.TransporteCerrado("sobre truncado")

    with pytest.raises(T.TransporteCerrado):
        T.con_reintentos(corrupto, dormir=lambda s: None)
    assert intentos["n"] == 1, "no se reintentó una corrupción"


# ==================== el respawn actualiza el sidecar ====================
def test_cada_respawn_registra_la_generacion_VIVA(tmp_path):
    """Sin esto el sidecar apuntaría a la generación muerta y el barrido
    diferido dejaría vivo justamente al trabajador colgado."""
    registrados = []
    c = canal_con(eco(), al_respawnear=lambda t: registrados.append(
        (t.generacion, t.pid)))
    try:
        c.pedir("https://x/k", {})
        c.respawnear()
        c.pedir("https://x/k", {})
        assert [g for g, _ in registrados] == [1, 2]
        assert registrados[0][1] != registrados[1][1]
        assert registrados[-1][1] == c.trabajador.pid
    finally:
        c.cerrar(plazo_s=2)


# ============ los hallazgos que la primera pasada no cubría ==============
def test_el_trabajador_completa_ESCRITURAS_PARCIALES(tmp_path):
    """Un solo `os.write` ignorando lo que efectivamente escribió dejaba la
    respuesta a medias: el padre esperaba la trama, vencía el deadline, y una
    falla del TRANSPORTE se convertía en reintento."""
    grande = {"velas": ["y" * 400 for _ in range(3000)]}      # ~1,2 MB
    c = canal_con(eco(200, grande), deadline_ms=15_000)
    try:
        r = c.pedir("https://x/k", {})
        assert r["ok"] and len(r["body"]["velas"]) == 3000
        # y varias seguidas por el MISMO trabajador: el buffer se llena y se
        # vacía muchas veces
        for _ in range(3):
            assert c.pedir("https://x/k", {})["ok"]
        assert c.generacion == 1, "no debería haber respawneado"
    finally:
        c.cerrar(plazo_s=3)


def test_los_descriptores_del_trabajador_son_NO_BLOQUEANTES(tmp_path):
    """`select` marca escribible cuando cabe AL MENOS UN BYTE, no el bloque."""
    import fcntl
    visto = str(tmp_path / "flags")

    def espia(url, p, ct, rt):
        # se ejecuta DENTRO del trabajador; sus dos tuberías son los únicos
        # descriptores abiertos además de 0/1/2
        estados = {}
        for fd in range(3, 256):
            try:
                estados[fd] = bool(fcntl.fcntl(fd, fcntl.F_GETFL)
                                   & os.O_NONBLOCK)
            except OSError:
                pass
        with open(visto, "w") as fh:
            fh.write(repr(estados))
        return (200, {})

    c = canal_con(espia)
    try:
        c.pedir("https://x/k", {})
        estados = eval(open(visto).read())
        assert len(estados) >= 2, (
            f"el trabajador debería conservar sus DOS tuberías: {estados}")
        assert all(estados.values()), (
            f"descriptores BLOQUEANTES en el trabajador: {estados}")
    finally:
        c.cerrar(plazo_s=2)


def test_una_generacion_cuyo_REGISTRO_fallo_no_queda_utilizable(tmp_path):
    """Asignar el trabajador antes de registrarlo dejaba viva una generación
    que el barrido no conocía, y el pedido siguiente devolvía éxito sobre un
    trabajador invisible."""
    vivos = []

    def registro_roto(t):
        vivos.append(t.pid)
        raise OSError(5, "EIO simulado")

    c = canal_con(eco(), al_respawnear=registro_roto)
    try:
        with pytest.raises(OSError):
            c.pedir("https://x/k", {})
        assert c.trabajador is None, "la generación NO puede quedar en uso"
        assert vivos and not P.vivo(vivos[0]), "y su proceso debe estar muerto"
    finally:
        c.cerrar(plazo_s=2)


def test_una_respuesta_de_ID_AJENO_no_deja_al_trabajador_vivo(tmp_path):
    """La validación tiene que estar DENTRO del bloque que limpia: el canal ya
    quedó demostrado corrupto."""
    def mentir(url, p, ct, rt):
        return (200, {"ok": True})

    c = canal_con(mentir)
    try:
        c.asegurar()
        pid = c.trabajador.pid
        real = T.validar_respuesta
        T.validar_respuesta = lambda *a: (_ for _ in ()).throw(
            T.TransporteCerrado("respuesta ajena simulada"))
        try:
            with pytest.raises(T.TransporteCerrado):
                c.pedir("https://x/k", {})
        finally:
            T.validar_respuesta = real
        assert c.trabajador is None and not P.vivo(pid)
    finally:
        c.cerrar(plazo_s=2)


def test_el_backoff_por_DEFECTO_espera_de_verdad(tmp_path):
    """`dormir=None` omitía TODA espera: cinco intentos en microsegundos contra
    el mismo endpoint, que es lo contrario de un backoff."""
    def siempre_falla():
        raise T.FalloDeRed(T.ERR_CONEXION)

    t0 = time.monotonic()
    with pytest.raises(T.FalloDeRed):
        # sin `dormir`: el default tiene que ser la espera interruptible
        T.con_reintentos(siempre_falla, azar=lambda a, b: 0.05, intentos=3)
    transcurrido = time.monotonic() - t0
    assert transcurrido >= 0.09, f"no esperó: {transcurrido:.4f}s"


def test_un_EMFILE_es_INTERNO_y_no_de_red(tmp_path):
    """`EMFILE` —descriptores agotados— es una falla LOCAL del trabajador.
    Clasificarla como `conexion` la hacía reintentable, así que el observador
    reintentaba cinco veces un problema suyo y seguía como si nada."""
    for numero, esperado in ((errno.EMFILE, T.ERR_INTERNO),
                             (errno.ENFILE, T.ERR_INTERNO),
                             (errno.ENOMEM, T.ERR_INTERNO),
                             (errno.EBADF, T.ERR_INTERNO),
                             (errno.ECONNREFUSED, T.ERR_CONEXION),
                             (errno.ETIMEDOUT, T.ERR_CONEXION),
                             (errno.EHOSTUNREACH, T.ERR_CONEXION)):
        assert W.clasificar(OSError(numero, os.strerror(numero)))[0] == \
            esperado, numero


def test_se_aplican_los_DOS_timeouts_congelados(tmp_path):
    """§15 congela `CONNECT_TIMEOUT` = 5 s y `READ_TIMEOUT` = 20 s, y usar el
    mayor para ambos deja la conexión sin su cota propia."""
    vistos = {}

    class ConexionEspia:
        def __init__(self, netloc, timeout=None):
            vistos["connect"] = timeout
            self.sock = self

        def settimeout(self, valor):
            vistos["read"] = valor

        def connect(self):
            pass

        def request(self, metodo, camino):
            vistos["camino"] = camino

        def getresponse(self):
            class R:
                status, reason, headers = 200, "OK", None

                def read(self, n):
                    return b"{}"
            return R()

        def close(self):
            pass

    real = W.http.client.HTTPSConnection
    W.http.client.HTTPSConnection = ConexionEspia
    try:
        W.obtener("https://host/fapi/v1/klines", {"symbol": "BTCUSDT"},
                  C.CONNECT_TIMEOUT_MS / 1000.0, C.READ_TIMEOUT_MS / 1000.0)
    finally:
        W.http.client.HTTPSConnection = real
    assert vistos["connect"] == C.CONNECT_TIMEOUT_MS / 1000.0
    assert vistos["read"] == C.READ_TIMEOUT_MS / 1000.0
    assert vistos["read"] != vistos["connect"], "no se aplicó el de conexión"
    assert "symbol=BTCUSDT" in vistos["camino"]


def test_el_encuadre_comparte_la_GRAMATICA_de_seccion_5(tmp_path):
    """Duplicarla divergía: `int(b"+5")` y `int(b"  5  ")` valen 5 en Python,
    así que la copia aceptaba longitudes que el lector canónico rechaza."""
    from modules.bot3.v9 import marco as M
    from modules.bot3.observador.estado import canon

    cuerpo = {"generacion": 1, "pedido": 1}
    assert T.enmarcar(cuerpo) == M.enmarcar(canon(cuerpo))

    payload = canon(cuerpo).encode()
    import hashlib
    h = hashlib.sha256(payload).hexdigest().encode()
    for cabeza in (b"+" + str(len(payload)).encode(),
                   b"  " + str(len(payload)).encode() + b"  ",
                   str(len(payload)).encode() + b"\n",
                   b"0" * 10 + str(len(payload)).encode()):
        with pytest.raises(T.TransporteCerrado, match="gramática|no cierra"):
            T.desenmarcar(cabeza + b"\t" + h + b"\t" + payload + b"\n")

    # y el hash en MAYÚSCULAS tampoco: la gramática exige `[0-9a-f]{64}`
    with pytest.raises(T.TransporteCerrado, match="gramática"):
        T.desenmarcar(str(len(payload)).encode() + b"\t" + h.upper()
                      + b"\t" + payload + b"\n")
