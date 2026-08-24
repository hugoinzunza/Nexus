"""Observador Bot3.v13 — gates de la capa registral de §20 (rev.34).

Cubre las partes de 47bis, 47quater, 47quinquies, 48quinquies y 48octies que
no necesitan procesos: los tres artefactos, sus schemas, la primitiva de
enlace exclusivo y la comparación por campos deterministas.

Las cuatro propiedades exigidas:

- nada se publica sin validar, y un documento corrupto NUNCA cuenta como
  éxito idempotente;
- el archivado no pisa historia previa;
- la reanudación con DOS RELOJES distintos da éxito idempotente;
- el arranque distingue por CÓDIGO, no por presencia.
"""
import json
import os

import pytest

from modules.bot3.observador import contrato as C
from modules.bot3.observador import diagnostico as D
from modules.bot3.observador.estado import canon, escribir_atomico, sha

# El contrato es el hash congelado real: la validación exige SHA-256, y un
# relleno no hexadecimal no sirve de fixture.
from modules.bot3.v9.contract import CONTRATO_HASH

IDENT = {"cohorte": "ensayo", "contrato": CONTRATO_HASH, "commit": "y" * 40}
OTRA = dict(IDENT, cohorte="otra")
SUP = D._sellar({"schema_version": 1, "cohorte": IDENT["cohorte"],
                 "contrato": IDENT["contrato"], "commit": IDENT["commit"],
                 "publicado_en": 1000})


def estado(tmp_path, nombre="estado"):
    d = str(tmp_path / nombre)
    os.makedirs(d, exist_ok=True)
    return d


# ==================== enlace exclusivo (§20.6.4) ====================
def test_el_enlace_exclusivo_no_sobrescribe_y_no_cruza_filesystems(tmp_path):
    """`os.replace` sobrescribiría en silencio, y comprobar `exists` antes de
    renombrar deja una ventana que otro proceso puede ganar. `link` resuelve
    las dos cosas en una operación atómica del kernel."""
    d = estado(tmp_path)
    a, b = os.path.join(d, "a"), os.path.join(d, "b")
    escribir_atomico(a, "primero")
    assert D.enlazar_exclusivo(a, b) is True
    assert not os.path.exists(a) and open(b).read() == "primero"

    escribir_atomico(a, "segundo")
    assert D.enlazar_exclusivo(a, b) is False       # EEXIST, no sobrescribe
    assert open(b).read() == "primero"              # la historia queda intacta
    assert not os.path.exists(a)                    # el origen se consume igual


def test_una_caida_entre_link_y_unlink_se_completa_por_dev_e_inodo(tmp_path):
    """El inodo SOLO no identifica un archivo: el mismo número existe en cada
    filesystem montado."""
    d = estado(tmp_path)
    a, b = os.path.join(d, "a"), os.path.join(d, "b")
    escribir_atomico(a, "x")
    os.link(a, b)                                   # CAÍDA justo acá
    assert D.completar_enlace_a_medias(a, b) is True
    assert not os.path.exists(a) and os.path.exists(b)

    # dos archivos DISTINTOS con el mismo destino no son media operación
    escribir_atomico(a, "otro contenido")
    with pytest.raises(D.Conflicto, match="DISTINTOS"):
        D.completar_enlace_a_medias(a, b)
    assert os.path.exists(a)                        # nada se tocó


# ==================== comparación determinista (§20.4.2.4) ====================
def test_la_reanudacion_con_DOS_RELOJES_da_exito_idempotente(tmp_path):
    """El caso que rev.33 hacía imposible: el proceso que retoma muestrea su
    propio reloj, así que comparar el documento ENTERO terminaba en fallo
    cerrado SIEMPRE."""
    d = estado(tmp_path)
    ruta, primera = D.publicar_incidencia(d, SUP, "a" * 64,
                                          D.CLAS_PRESERVADO, 111)
    # CAÍDA antes de retirar el sidecar; otro proceso retoma con OTRO reloj
    ruta2, vigente = D.publicar_incidencia(d, SUP, "a" * 64,
                                           D.CLAS_PRESERVADO, 999)
    assert ruta2 == ruta                            # ruta determinista
    assert vigente["ocurrido_en"] == 111            # el de la PRIMERA
    assert vigente == primera
    assert len(os.listdir(os.path.join(d, D.CARPETA_DIAGNOSTICOS))) == 1

    # y un campo DETERMINISTA distinto sí es conflicto
    with pytest.raises(D.Conflicto, match="clasificacion"):
        D.publicar_incidencia(d, SUP, "a" * 64, D.CLAS_CORRUPTO, 999)


def test_la_acreditacion_tambien_conserva_su_instante(tmp_path):
    """Misma regla: `acreditado_en` queda fuera de la comparación."""
    d = estado(tmp_path)
    _, primera = D.publicar_acreditacion(d, IDENT, "b" * 64, "hugo",
                                         "revisado el libro", 500)
    _, vigente = D.publicar_acreditacion(d, IDENT, "b" * 64, "hugo",
                                         "revisado el libro", 700)
    assert vigente["acreditado_en"] == 500 and vigente == primera
    # otro operador sobre el MISMO diagnóstico es conflicto, no idempotencia
    with pytest.raises(D.Conflicto, match="acreditado_por"):
        D.publicar_acreditacion(d, IDENT, "b" * 64, "otro",
                                "revisado el libro", 700)


def test_un_documento_CORRUPTO_en_la_ruta_no_es_exito_idempotente(tmp_path):
    """Si no, la recuperación aceptaría cualquier basura que ocupara el
    nombre."""
    d = estado(tmp_path)
    ruta = D.ruta_incidencia(d, SUP["checksum"], "a" * 64)
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    escribir_atomico(ruta, '{"schema_version": 1}')
    with pytest.raises(D.DocumentoInvalido):
        D.publicar_incidencia(d, SUP, "a" * 64, D.CLAS_PRESERVADO, 111)


def test_un_tmp_huerfano_se_descarta_y_no_es_la_incidencia(tmp_path):
    d = estado(tmp_path)
    ruta = D.ruta_incidencia(d, SUP["checksum"], "a" * 64)
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    escribir_atomico(ruta + ".tmp", "basura de una caída a mitad")
    _, cuerpo = D.publicar_incidencia(d, SUP, "a" * 64, D.CLAS_PRESERVADO, 5)
    assert cuerpo["ocurrido_en"] == 5
    assert not os.path.exists(ruta + ".tmp")


# ==================== el diagnóstico previo ILEGIBLE ====================
def test_la_incidencia_se_publica_sobre_un_diagnostico_ILEGIBLE(tmp_path):
    """§20.4.2.3: la identidad sale de `supervision.json` y el documento previo
    se identifica por sus BYTES CRUDOS, porque sus campos internos pueden estar
    rotos, ausentes o mentir."""
    d = estado(tmp_path)
    roto = os.path.join(d, C.ARCHIVO_FALLO_CERRADO)
    escribir_atomico(roto, '{"cohorte": "AJENA", "checksum": ')   # ni JSON es
    sha_crudo = D.sha_de_bytes(roto)
    ruta, cuerpo = D.publicar_incidencia(d, SUP, sha_crudo, D.CLAS_CORRUPTO, 7)
    assert cuerpo["cohorte"] == IDENT["cohorte"]     # NO la del documento roto
    assert cuerpo["diagnostico_sha256"] == sha_crudo
    assert os.path.exists(roto)                      # no se tocó
    assert D.validar_incidencia(json.load(open(ruta)), ruta)

    # sin diagnóstico previo, el segundo hash es el de la cadena vacía
    d2 = estado(tmp_path, "sin")
    _, c2 = D.publicar_incidencia(
        d2, SUP, D.sha_de_bytes(os.path.join(d2, C.ARCHIVO_FALLO_CERRADO)),
        D.CLAS_CORRUPTO, 7)
    assert c2["diagnostico_sha256"] == D.SHA_VACIO


# ==================== arranque: código, no presencia (§20.6.4) ====================
def test_el_arranque_distingue_por_CODIGO_no_por_presencia(tmp_path):
    """rev.20 rechazaba cualquier presencia y el daemon escribía un
    diagnóstico también antes de salir `2`: `EBUSY → codigo=2 → reinicio →
    sale 1`. Nunca se llegaba al segundo intento y `MAX_TRANSITORIOS` era
    inoperante."""
    d = estado(tmp_path)
    assert D.bloquea_arranque(d, IDENT) is None      # nada

    # `codigo: 2` NO bloquea, y la serie avanza hasta la cota
    for n in range(1, C.MAX_TRANSITORIOS):
        D.publicar_diagnostico(d, D.diagnostico(
            IDENT, D.MOTIVO_EXCEPCION, 2, 10, transitorios=n,
            excepcion="BlockingIOError: EBUSY"))
        assert D.bloquea_arranque(d, IDENT) is None, f"la serie murió en {n}"

    # el quinto SÍ: la cota existe
    D.publicar_diagnostico(d, D.diagnostico(
        IDENT, D.MOTIVO_EXCEPCION, 2, 10, transitorios=C.MAX_TRANSITORIOS,
        excepcion="BlockingIOError: EBUSY"))
    assert D.bloquea_arranque(d, IDENT)["transitorios"] == C.MAX_TRANSITORIOS

    # `codigo: 1` bloquea de entrada
    D.publicar_diagnostico(d, D.diagnostico(
        IDENT, D.MOTIVO_SENAL, 1, 10, senal=9, estado_crudo=137))
    assert D.bloquea_arranque(d, IDENT)["motivo"] == D.MOTIVO_SENAL


def test_un_diagnostico_de_OTRA_identidad_falla_cerrado(tmp_path):
    d = estado(tmp_path)
    D.publicar_diagnostico(d, D.diagnostico(OTRA, D.MOTIVO_WRAPPER, 1, 10))
    with pytest.raises(D.DocumentoInvalido, match="otra identidad"):
        D.bloquea_arranque(d, IDENT)


def test_un_diagnostico_corrupto_bloquea_en_vez_de_ignorarse(tmp_path):
    d = estado(tmp_path)
    cuerpo = D.diagnostico(IDENT, D.MOTIVO_WRAPPER, 1, 10)
    cuerpo["codigo"] = 2                             # checksum ya no cuadra
    escribir_atomico(os.path.join(d, C.ARCHIVO_FALLO_CERRADO), canon(cuerpo))
    with pytest.raises(D.DocumentoInvalido, match="checksum"):
        D.bloquea_arranque(d, IDENT)


# ==================== archivado append-only (§20.6.4) ====================
def test_el_archivado_no_pisa_historia_previa(tmp_path):
    """Renombrar siempre al mismo `.archivado` era archivar y perder la
    historia a la vez."""
    d = estado(tmp_path)
    rutas = []
    for instante in (10, 20):
        cuerpo = D.diagnostico(IDENT, D.MOTIVO_EXCEPCION, 2, instante,
                               transitorios=1, excepcion="EBUSY")
        D.publicar_diagnostico(d, cuerpo)
        rutas.append(D.archivar_diagnostico(d, cuerpo))
    assert len(set(rutas)) == 2
    assert all(os.path.exists(r) for r in rutas)
    assert not os.path.exists(os.path.join(d, C.ARCHIVO_FALLO_CERRADO))

    # colisión forzada: falla cerrado por EEXIST del `link`, no por una
    # comprobación previa que otro proceso podría ganar
    cuerpo = D.diagnostico(IDENT, D.MOTIVO_EXCEPCION, 2, 10, transitorios=1,
                           excepcion="EBUSY")
    D.publicar_diagnostico(d, cuerpo)
    with pytest.raises(D.Conflicto, match="no se pisa historia"):
        D.archivar_diagnostico(d, cuerpo)


def test_una_caida_entre_link_y_unlink_del_archivado_se_completa(tmp_path):
    d = estado(tmp_path)
    cuerpo = D.diagnostico(IDENT, D.MOTIVO_WRAPPER, 1, 42)
    D.publicar_diagnostico(d, cuerpo)
    origen = os.path.join(d, C.ARCHIVO_FALLO_CERRADO)
    destino = os.path.join(d, D.CARPETA_DIAGNOSTICOS,
                           f"fallo_cerrado.42.{cuerpo['checksum'][:8]}.json")
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    os.link(origen, destino)                         # CAÍDA justo acá
    assert D.archivar_diagnostico(d, cuerpo) == destino
    assert not os.path.exists(origen)


# ==================== vectores adversariales por campo ====================
def test_vectores_adversariales_del_diagnostico(tmp_path):
    """Comprobar solo que el campo EXISTE es fail-open. Los tipos y formatos
    se exigen uno por uno."""
    base = D.diagnostico(IDENT, D.MOTIVO_EXCEPCION, 1, 10, excepcion="X")
    vectores = {
        "schema_ajeno": dict(base, schema_version=99),
        "motivo_desconocido": dict(base, motivo="n_cierres"),
        "codigo_crudo_de_senal": dict(base, codigo=137),
        "codigo_cero": dict(base, codigo=0),
        "ocurrido_bool": dict(base, ocurrido_en=True),
        "ocurrido_texto": dict(base, ocurrido_en="10"),
        "transitorios_negativos": dict(base, transitorios=-1),
        "transitorios_bool": dict(base, transitorios=True),
        "contrato_no_sha": dict(base, contrato="a" * 63),
        "cohorte_vacia": dict(base, cohorte="   "),
        "commit_ausente": {k: v for k, v in base.items() if k != "commit"},
        "excepcion_vacia": dict(base, excepcion=""),
        "senal_sin_motivo_senal": dict(base, senal=9),
        "supervision_sin_su_motivo": dict(base, supervision_checksum="a" * 64),
        "estado_crudo_texto": dict(base, estado_crudo="137"),
    }
    for nombre, cuerpo in vectores.items():
        sellado = D._sellar(cuerpo)                  # checksum COHERENTE
        with pytest.raises(D.DocumentoInvalido):
            D.validar_diagnostico(sellado, nombre)

    # y los que faltan por motivo
    for motivo, falta in ((D.MOTIVO_SENAL, "senal"),
                          (D.MOTIVO_SUPERVISOR, "supervision_checksum"),
                          (D.MOTIVO_TRANSITORIOS, "excepcion")):
        cuerpo = D._sellar(dict(base, motivo=motivo))
        cuerpo.pop(falta, None)
        with pytest.raises(D.DocumentoInvalido):
            D.validar_diagnostico(D._sellar(cuerpo), motivo)

    # el checksum alterado se detecta aunque todo lo demás valide
    malo = dict(base, ocurrido_en=11)
    with pytest.raises(D.DocumentoInvalido, match="checksum"):
        D.validar_diagnostico(malo)


def test_vectores_adversariales_de_incidencia_y_acreditacion(tmp_path):
    inc = D._sellar({
        "schema_version": 1, **{k: IDENT[k] for k in IDENT},
        "supervision_checksum": "a" * 64, "diagnostico_sha256": "b" * 64,
        "clasificacion": D.CLAS_CORRUPTO, "ocurrido_en": 1})
    acr = D._sellar({
        "schema_version": 1, **{k: IDENT[k] for k in IDENT},
        "diagnostico_checksum": "c" * 64, "acreditado_por": "hugo",
        "motivo_humano": "porque sí", "acreditado_en": 1})

    for cuerpo, validar, vectores in (
        (inc, D.validar_incidencia, {
            "clasificacion_ajena": dict(inc, clasificacion="otra"),
            "supervision_no_sha": dict(inc, supervision_checksum="a" * 63),
            "diagnostico_no_sha": dict(inc, diagnostico_sha256=None),
            "instante_bool": dict(inc, ocurrido_en=True),
            "schema_ajeno": dict(inc, schema_version=2)}),
        (acr, D.validar_acreditacion, {
            "operador_vacio": dict(acr, acreditado_por="  "),
            "motivo_vacio": dict(acr, motivo_humano=""),
            "motivo_ausente": {k: v for k, v in acr.items()
                               if k != "motivo_humano"},
            "checksum_citado_no_sha": dict(acr, diagnostico_checksum="c"),
            "instante_texto": dict(acr, acreditado_en="1")}),
    ):
        assert validar(cuerpo)                       # el bueno valida
        for nombre, malo in vectores.items():
            with pytest.raises(D.DocumentoInvalido):
                validar(D._sellar(malo), nombre)
