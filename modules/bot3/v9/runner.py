"""Bot3.v9 — ensamblado: fuentes → almacenes → motor → ledger.

Único punto donde se leen datos. Sin credenciales ni ejecutor: solo klines
públicas versionadas y el push del VPS (CF-22: prioridad versionado > push).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil

from . import store as S
from . import contract as CT
from .contract import CONTRATO_HASH, GENESIS_H4, MERCADOS, TF_MS, canon, sha256_hex
from .engine import DUR_M15, Motor
from .ledger import Ledger

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
TF_ARCHIVO = {"15m": "15m", "4h": "4h"}


SHA_GIT = 40                     # SHA-1 canónico de Git


def validar_commit(commit: str, root: str) -> str:
    """CF-28: el ancla de provenance debe ser un commit Git REAL.

    Exige SHA-1 canónico (40 hex minúscula) y, si el runtime tiene
    metadata Git, que el objeto exista y sea un commit. Sin `.git` (por
    ejemplo en un contenedor de despliegue) se acepta el SHA bien formado y
    la verificación queda delegada al proceso de build, que es el que
    conoce el árbol de origen."""
    if not isinstance(commit, str) or len(commit) != SHA_GIT or \
            any(c not in "0123456789abcdef" for c in commit):
        raise ValueError(
            f"`commit` debe ser un SHA-1 Git canónico (40 hex minúscula), "
            f"no {commit!r}")
    if _hay_git(root):
        import subprocess
        r = subprocess.run(["git", "-C", root, "cat-file", "-e",
                            f"{commit}^{{commit}}"],
                           capture_output=True)
        if r.returncode != 0:
            raise ValueError(
                f"`commit` {commit} no existe como commit en {root}")
        head = commit_actual(root)
        if head is not None and head != commit:
            # El ancla debe ser el codigo EJECUTADO, no cualquier commit del
            # historial: si no, un commit antiguo (que ni siquiera contiene el
            # snapshot) podria anclar el estado.
            raise ValueError(
                f"`commit` {commit} no es el HEAD ejecutado ({head})")
    return commit


ALCANCE_CODIGO = "modules/bot3/v9"


def validar_arbol_limpio(root: str, alcance: str = ALCANCE_CODIGO) -> None:
    """CF-28: el commit debe autenticar el CÓDIGO EJECUTADO.

    Verificar que el argumento es el HEAD no basta: el árbol de trabajo puede
    tener cambios sin commitear en el alcance de Bot3, y entonces el libro lo
    produce código que ese commit no describe."""
    if not _hay_git(root):
        return
    import subprocess
    r = subprocess.run(["git", "-C", root, "status", "--porcelain", "--",
                        alcance], capture_output=True, text=True)
    sucio = [l for l in r.stdout.splitlines() if l.strip()]
    if sucio:
        raise ValueError(
            f"el árbol de {alcance} tiene cambios sin commitear: el commit "
            f"no autentica el código ejecutado — "
            f"{', '.join(l[3:] for l in sucio[:4])}")


def blob_en_commit(root: str, commit: str, ruta: str) -> str | None:
    """SHA del blob que ese commit tiene en `ruta` (None si no lo contiene)."""
    import subprocess
    rel = os.path.relpath(ruta, root)
    r = subprocess.run(["git", "-C", root, "rev-parse", f"{commit}:{rel}"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def blob_del_archivo(root: str, ruta: str) -> str | None:
    import subprocess
    r = subprocess.run(["git", "-C", root, "hash-object", ruta],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def validar_snapshot_en_commit(root: str, commit: str, ruta: str,
                               permitir_externo: bool = False) -> None:
    """CF-28: los BYTES del snapshot deben corresponder a ese commit.

    Verificar que el commit existe no basta: debe CONTENER el snapshot y su
    contenido debe coincidir. Si el snapshot vive fuera del repositorio, la
    verificación es imposible y se exige `permitir_externo` explícito — nunca
    se omite en silencio."""
    if not _hay_git(root):
        if not permitir_externo:
            raise ValueError(
                f"sin metadata Git en {root} no se puede autenticar "
                f"{ruta}; pasar `permitir_snapshot_externo=True` si el "
                f"build lo verifica por fuera")
        return
    esperado = blob_en_commit(root, commit, ruta)
    if esperado is None:
        if permitir_externo:
            return
        raise ValueError(
            f"el commit {commit[:12]}… no contiene {ruta}")
    actual = blob_del_archivo(root, ruta)
    if actual != esperado:
        raise ValueError(
            f"los bytes de {ruta} no corresponden al commit {commit[:12]}…: "
            f"{actual} != {esperado}")


def _hay_git(root: str) -> bool:
    """Metadata Git disponible. Se consulta a `git`, no a `.git/`: en un
    worktree `.git` es un ARCHIVO, no un directorio."""
    import subprocess
    r = subprocess.run(["git", "-C", root, "rev-parse", "--git-dir"],
                       capture_output=True)
    return r.returncode == 0


def commit_actual(root: str) -> str | None:
    """`HEAD` del repositorio, si el runtime tiene metadata Git."""
    if not _hay_git(root):
        return None
    import subprocess
    r = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def ruta_snapshot(root: str, mercado: str, tf: str) -> str:
    return os.path.join(root, "data", f"klines_{mercado}_{TF_ARCHIVO[tf]}.json")


def sha_snapshot(ruta: str) -> str | None:
    """SHA-256 del archivo de snapshot versionado (provenance CF-28)."""
    if not os.path.exists(ruta):
        return None
    h = hashlib.sha256()
    with open(ruta, "rb") as fh:
        for bloque in iter(lambda: fh.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def leer_versionado(root: str, mercado: str, tf: str) -> list[dict]:
    ruta = ruta_snapshot(root, mercado, tf)
    try:
        with open(ruta, encoding="utf-8") as fh:
            filas = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return []
    return filas if isinstance(filas, list) else []


MANIFIESTO = "MANIFIESTO.json"


CARPETA_ALMACENES = "almacenes"
CARPETA_STAGING = "almacenes.new"


def ruta_estado(estado_dir: str, mercado: str, tf: str,
                carpeta: str = CARPETA_ALMACENES) -> str:
    """Los 14 almacenes viven en UNA carpeta, para poder publicarlos con un
    solo rename atómico en el nacimiento (diseño rev.8 §4)."""
    return os.path.join(estado_dir, carpeta, f"{mercado}_{tf}.jsonl")


def _fsync_dir(ruta: str) -> None:
    fd = os.open(ruta, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def leer_manifiesto(estado_dir: str) -> dict:
    """Almacenes que este estado_dir DECLARA tener sellados. Distingue las
    tres situaciones operacionales (B-6):
      - directorio nuevo (sin manifiesto)  → creación completa;
      - recuperación (declarado y presente) → obligatorio, se rehidrata;
      - directorio parcial (declarado y ausente) → FALLO CERRADO."""
    ruta = os.path.join(estado_dir, MANIFIESTO)
    if not os.path.exists(ruta):
        return {}
    with open(ruta, encoding="utf-8") as fh:
        alm = json.load(fh).get("almacenes", {})
    return alm if isinstance(alm, dict) else {n: {} for n in alm}


def escribir_manifiesto(estado_dir: str, almacenes: dict,
                        cohorte: dict | None = None) -> None:
    """El manifiesto GUARDA la provenance de cada almacén (ancla, snapshot,
    commit y hash inicial) para poder reemitir `nacimiento` de forma
    idempotente si el proceso cayó entre la creación y el append al
    ledger."""
    os.makedirs(estado_dir, exist_ok=True)
    ruta_m = os.path.join(estado_dir, MANIFIESTO)
    # Se lee ANTES de tocar el archivo: abrirlo en modo "w" lo truncaba y la
    # cohorte que se pretendía conservar ya no estaba.
    previo = {}
    if os.path.exists(ruta_m):
        try:
            with open(ruta_m, encoding="utf-8") as fh:
                previo = json.load(fh)
        except (OSError, json.JSONDecodeError):
            previo = {}
    cuerpo = {"almacenes": almacenes}
    conservada = cohorte if cohorte is not None else previo.get("cohorte")
    if conservada:
        cuerpo["cohorte"] = conservada
    # Escritura ATÓMICA: temporal + fsync + replace. Un fallo a mitad no puede
    # dejar un manifiesto truncado o sin cohorte.
    tmp = ruta_m + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cuerpo, fh, sort_keys=True, separators=(",", ":"))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, ruta_m)


PARAMS_CONGELADOS = ("GENESIS_H4", "EPOCA_M15_MIN_VELAS", "WATERMARK_LOCAL_N",
                     "WATERMARK_EXCHANGE_Q", "WATERMARK_EXCHANGE_N",
                     "STRUCT_PIV", "INT_PIV", "SWEEP_LOOKBACK_SWINGS",
                     "DIR_EXPIRA_H4", "TTL_ZONA_H4", "DEADLINE_M15",
                     "VENTANA_IBOS_M15", "OB_LOOKBACK", "SL_BUFFER", "RR_MIN",
                     "FEE_MAKER", "FEE_TAKER", "SLIPPAGE_STOP", "FUNDING_RATE",
                     "T_CORTE", "CORTE_N_CIERRES", "CORTE_MIN_SEMANAS_ISO",
                     "CORTE_ADMIN_GRACIA_MS", "BOOTSTRAP_REPLICAS",
                     "BOOTSTRAP_SEMILLA")


def huella_parametros() -> str:
    """SHA-256 de los parámetros congelados efectivos del contrato."""
    return sha256_hex(canon({k: getattr(CT, k) for k in PARAMS_CONGELADOS}))


def identidad_cohorte(mercados, commit: str, bootstrap_hasta, ledger_ruta):
    """Identidad que define ESTA cohorte. Cambiar cualquiera de estos
    valores es una cohorte distinta (CF-11/CF-21)."""
    return {"contrato": CONTRATO_HASH, "commit": commit,
            "universo": sorted(mercados),
            "bootstrap_hasta": bootstrap_hasta,
            "ledger_ruta": ledger_ruta,
            "parametros_sha": huella_parametros()}


def validar_cohorte(estado_dir: str, identidad: dict) -> None:
    """FAIL-FAST: se compara ANTES de crear el ledger y de cualquier append.
    Antes, reiniciar con otra `T_frontera` alcanzaba a escribir una segunda
    `frontera` y dejaba el ledger modificado (fail-late)."""
    ruta = os.path.join(estado_dir, MANIFIESTO)
    if not os.path.exists(ruta):
        return
    with open(ruta, encoding="utf-8") as fh:
        previa = json.load(fh).get("cohorte")
    if not previa:
        return
    difs = sorted(k for k in set(previa) | set(identidad)
                  if previa.get(k) != identidad.get(k))
    if difs:
        raise ValueError(
            f"la identidad de la cohorte en {estado_dir} no coincide en "
            f"{difs}: reiniciar con otra configuración sería una cohorte "
            f"distinta")


def construir_almacenes(root: str, mercados=MERCADOS, tf: str = "15m",
                        limite: int | None = None,
                        extra: dict | None = None,
                        estado_dir: str | None = None,
                        ledger=None,
                        commit_snapshot: str | None = None,
                        exigir_universo: bool = False,
                        permitir_snapshot_externo: bool = False,
                        carpeta: str = CARPETA_ALMACENES,
                        publicar_manifiesto: bool = True,
                        registro_out: dict | None = None) -> dict:
    """Construye los almacenes ingiriendo el snapshot versionado (CF-28) y,
    opcionalmente, velas adicionales (push) por mercado.

    `limite` recorta las velas OFRECIDAS (no el ancla): sirve para el gate de
    determinismo de génesis — distintas profundidades de carga deben producir
    el mismo libro sobre el tramo común."""
    almacenes = {}
    dur = TF_MS[tf]
    declarados = leer_manifiesto(estado_dir) if estado_dir else {}
    registro: dict = dict(declarados)
    huecos: list = []
    for mercado in mercados:
        nombre = f"{mercado}_{tf}"
        declarado = estado_dir is not None and nombre in declarados
        filas = leer_versionado(root, mercado, tf)
        if not filas:
            # Un mercado DECLARADO no puede desaparecer del universo en
            # silencio por una ausencia transitoria del snapshot fuente:
            # fallo cerrado (antes se hacía `continue` y `mercados_ok` se
            # reducía sin dejar rastro).
            if declarado:
                raise FileNotFoundError(
                    f"snapshot fuente ausente para {nombre}, que el "
                    f"manifiesto de {estado_dir} declara sellado")
            if estado_dir or exigir_universo:
                # El universo es parte de la identidad de la cohorte: no
                # puede pasar de 7 a 6 mercados en silencio ni en el PRIMER
                # arranque (antes se hacía `continue`).
                raise FileNotFoundError(
                    f"snapshot fuente ausente para {nombre}: el universo "
                    f"declarado exige ese mercado")
            continue
        filas = sorted(filas, key=lambda r: int(r["t"]))
        if tf == "4h":
            filas = [r for r in filas if int(r["t"]) >= GENESIS_H4]
            ancla = GENESIS_H4
        else:
            ancla = int(filas[0]["t"])
        if estado_dir:
            # RECUPERACIÓN (B-6): si el manifiesto DECLARA este almacén, su
            # archivo es obligatorio (fallo cerrado si desapareció); si no
            # está declarado, es primer arranque y se crea.
            ruta = ruta_estado(estado_dir, mercado, tf, carpeta)
            # La provenance SIEMPRE nombra la ruta DEFINITIVA: durante el
            # nacimiento el archivo vive en staging, pero el evento
            # `nacimiento` no puede citar una ubicación transitoria — sería
            # otro payload para el mismo `event_id` al reprocesar.
            ruta_prov = ruta_estado(estado_dir, mercado, tf)
            if declarado:
                # CF-28: en una RECUPERACIÓN declarada, el snapshot debe ser
                # el mismo que se registró al nacer. Cargar uno distinto
                # cambiaría el ancla y la historia bajo un estado sellado.
                prov = declarados[nombre]
                sha_actual = sha_snapshot(ruta_snapshot(root, mercado, tf))
                sha_reg = prov.get("snapshot_sha256")
                commit_reg = prov.get("commit_snapshot")
                if not sha_reg or not commit_reg:
                    raise ValueError(
                        f"provenance incompleta para {nombre} en el "
                        f"manifiesto: falta snapshot_sha256 o commit_snapshot")
                if sha_actual != sha_reg:
                    raise ValueError(
                        f"snapshot de {nombre} cambió desde el nacimiento: "
                        f"{sha_actual} != {sha_reg} (registrado)")
                if commit_snapshot is not None and commit_snapshot != commit_reg:
                    raise ValueError(
                        f"commit del snapshot de {nombre} no coincide: "
                        f"{commit_snapshot} != {commit_reg} (registrado)")
            alm = S.Almacen.cargar(mercado, tf, ruta, requerido=declarado)
            if declarado:
                # PREFIJO DE NACIMIENTO (rev.8 §3). El manifiesto ya no guarda
                # el `head` físico —era su único campo mutable, y el primer
                # push lo invalidaba—, sino el prefijo inmutable por CF-28. El
                # sufijo posterior lo autentica la propia cadena, que `cargar`
                # revalida entera desde SEMILLA.
                #
                # La detección de intercambio se conserva: el prefijo deriva
                # del snapshot de ESE mercado, así que dos almacenes cruzados
                # tienen prefijos distintos.
                prov_n = declarados[nombre]
                cuenta = prov_n.get("snapshot_record_count")
                cabeza = prov_n.get("snapshot_head")
                if cuenta is None or not cabeza:
                    raise ValueError(
                        f"provenance incompleta para {nombre}: falta "
                        f"snapshot_record_count o snapshot_head")
                if len(alm.registros) < cuenta:
                    raise ValueError(
                        f"el archivo de {nombre} está truncado: "
                        f"{len(alm.registros)} registros < {cuenta} del "
                        f"prefijo de nacimiento")
                real = alm.registros[cuenta - 1]["hash_acum"]
                if real != cabeza:
                    raise ValueError(
                        f"el archivo de {nombre} no corresponde: prefijo de "
                        f"nacimiento {real[:12]}… != {cabeza[:12]}… "
                        f"(registrado)")
            if not alm.registros:
                alm.nacer_en(ancla)
            if commit_snapshot:
                validar_snapshot_en_commit(
                    root, commit_snapshot, ruta_snapshot(root, mercado, tf),
                    permitir_externo=permitir_snapshot_externo)
            if nombre not in registro:
                snap = ruta_snapshot(root, mercado, tf)
                registro[nombre] = {
                    "mercado": mercado, "tf": tf, "ancla": int(ancla),
                    "ruta": ruta_prov, "snapshot_ruta": snap,
                    "snapshot_sha256": sha_snapshot(snap),
                    "commit_snapshot": commit_snapshot or (
                        ledger.commit if ledger is not None else "dev"),
                    "hash_acum_inicial": S.SEMILLA,
                    # `snapshot_record_count` / `snapshot_head` se completan
                    # al terminar el nacimiento, más abajo.
                }
        else:
            alm = S.Almacen(mercado, tf)
            alm.nacer_en(ancla)
        ofrecidas = filas if limite is None else filas[-limite:]
        # El ancla manda: nada anterior puede entrar (CF-22/CF-28).
        alm.ofrecer(ofrecidas, "versionado")
        if extra and mercado in extra:
            alm.ofrecer(extra[mercado], "push")
        alm.drenar()
        while True:
            reg_hueco = alm.declarar_hueco_local()
            if reg_hueco is None:
                break
            huecos.append((mercado, reg_hueco))
        alm.huecos_declarados = [h for m, h in huecos if m == mercado]
        if estado_dir and nombre in registro \
                and registro[nombre].get("snapshot_head") is None:
            # NACIMIENTO recién completado: el prefijo es lo que el almacén
            # tiene ahora, y a partir de acá es inmutable.
            registro[nombre]["snapshot_record_count"] = len(alm.registros)
            registro[nombre]["snapshot_head"] = alm.head
        almacenes[mercado] = alm
    if estado_dir:
        if registro_out is not None:
            registro_out.update(registro)
        if publicar_manifiesto:
            escribir_manifiesto(estado_dir, registro)
    if ledger is not None:
        # CF-28: se reemite el `nacimiento` de TODO almacén del manifiesto de
        # esta TF. Es idempotente por `event_id`, así que un crash entre la
        # escritura del manifiesto y el append al ledger no pierde el evento:
        # el siguiente arranque lo repone desde la provenance guardada.
        for nombre, prov in sorted(registro.items()):
            if prov.get("tf") != tf:
                continue
            ledger.append("nacimiento", mercado=prov["mercado"], tf=prov["tf"],
                          effective_at=prov["ancla"], ruta=prov.get("ruta"),
                          snapshot_ruta=prov.get("snapshot_ruta"),
                          snapshot_sha256=prov.get("snapshot_sha256"),
                          commit_snapshot=prov.get("commit_snapshot"),
                          hash_acum_inicial=prov.get("hash_acum_inicial"))
        for alm in almacenes.values():       # CF-26: incidencias de ingestión
            for inc in alm.incidencias:
                ledger.append(inc["tipo"], mercado=inc["mercado"],
                              tf=inc["tf"], effective_at=inc["t"],
                              id=inc["contenido_sha"])
            alm.incidencias.clear()
    return almacenes


def correr(root: str = ROOT, mercados=MERCADOS, hasta: int | None = None,
           desde: int | None = None, limite: int | None = None,
           ledger_ruta: str | None = None, commit: str = "dev",
           bootstrap_hasta: int | None = None,
           reloj_ms: int | None = None,
           estado_dir: str | None = None,
           permitir_snapshot_externo: bool = False) -> tuple[Motor, Ledger]:
    """Corre el motor por lotes globales de `close_time` M15.

    Con `estado_dir`, los almacenes se PERSISTEN y se rehidratan en el
    siguiente arranque (B-6): un reinicio real reutiliza el push ya sellado
    en vez de reconstruirlo."""
    identidad = None
    if estado_dir:
        # MODO PERSISTENTE (cohorte real): prohibido todo lo que produzca una
        # historia distinta bajo la misma identidad.
        if limite is not None:
            raise ValueError(
                "`limite` está prohibido con `estado_dir`: recorta el "
                "almacén y produce una historia distinta bajo la misma "
                "identidad de cohorte")
        if desde is not None:
            raise ValueError(
                "`desde` está prohibido con `estado_dir`: saltarse lotes "
                "impide reconstruir causalmente el estado del motor")
        if bootstrap_hasta is None:
            raise ValueError(
                "una cohorte forward exige `bootstrap_hasta` (T_frontera): "
                "sin frontera no hay separación backtest/forward")
        if ledger_ruta is None:
            raise ValueError(
                "con `estado_dir` hay que persistir el ledger "
                "(`ledger_ruta`): si no, la cohorte no sobrevive al reinicio")
        # CF-28 sin excepciones: no hay bandera para saltarse esto. Una
        # cohorte evaluable NO puede arrancar con código sin autenticar.
        validar_arbol_limpio(ROOT)
        # Un ancla de provenance tiene que ser un commit Git real y el HEAD
        # ejecutado (CF-28), validado contra el repositorio del CÓDIGO.
        validar_commit(commit, ROOT)
        # FAIL-FAST: la identidad de la cohorte se compara ANTES de crear el
        # ledger, para que un reinicio con otra configuración no alcance a
        # escribir nada.
        identidad = identidad_cohorte(mercados, commit, bootstrap_hasta,
                                      ledger_ruta)
        validar_cohorte(estado_dir, identidad)
        # B1 (re-auditoría 2): la identidad se PERSISTE aquí, antes del
        # ledger y antes de crear un solo almacén. Escribirla al final dejaba
        # una ventana real: si el primer arranque materializaba M15 y moría
        # construyendo H4, el manifiesto quedaba sin `cohorte` y el arranque
        # siguiente aceptaba otra frontera sobre el mismo estado.
        escribir_manifiesto(estado_dir, leer_manifiesto(estado_dir), identidad)
    led = Ledger(ledger_ruta, commit=commit)
    # El commit del despliegue SÍ viaja a la construcción: es lo que activa
    # la verificación CF-28 en la ruta productiva.
    comun = dict(estado_dir=estado_dir, ledger=led, commit_snapshot=commit,
                 exigir_universo=True,
                 permitir_snapshot_externo=permitir_snapshot_externo)
    nacimiento = bool(estado_dir) and not leer_manifiesto(estado_dir)
    if nacimiento:
        # NACIMIENTO ATÓMICO (rev.8 §4). Los 14 almacenes se materializan en
        # `almacenes.new/` y se publican con UN solo rename: catorce renames
        # dejaban, ante una caída, unos archivos definitivos y otros no.
        #
        # El manifiesto es el ÚNICO testigo de nacimiento. Si no existe, todo
        # resto previo se descarta: `almacenes.new/` se borra y `almacenes/`
        # —que no puede provenir de un nacimiento publicado— va a cuarentena.
        stage = os.path.join(estado_dir, CARPETA_STAGING)
        firme = os.path.join(estado_dir, CARPETA_ALMACENES)
        if os.path.isdir(stage):
            shutil.rmtree(stage)
        if os.path.isdir(firme):
            destino = os.path.join(
                estado_dir, f"{CARPETA_ALMACENES}.cuarentena")
            n = 0
            while os.path.exists(destino if n == 0 else f"{destino}.{n}"):
                n += 1
            os.replace(firme, destino if n == 0 else f"{destino}.{n}")
        os.makedirs(stage, exist_ok=True)
        registro: dict = {}
        naciendo = dict(comun, carpeta=CARPETA_STAGING,
                        publicar_manifiesto=False, registro_out=registro)
        m15 = construir_almacenes(root, mercados, "15m", limite, **naciendo)
        h4 = construir_almacenes(root, mercados, "4h", limite, **naciendo)
        for mapa in (m15, h4):
            for alm in mapa.values():
                alm.sincronizar()
        _fsync_dir(stage)
        os.replace(stage, firme)                     # ← ATÓMICO, uno solo
        _fsync_dir(estado_dir)
        # Los almacenes quedan apuntando al staging: se reapunta al definitivo
        # (la provenance ya nombraba el definitivo).
        for tf_n, mapa in (("15m", m15), ("4h", h4)):
            for mercado, alm in mapa.items():
                alm.ruta = ruta_estado(estado_dir, mercado, tf_n)
        escribir_manifiesto(estado_dir, registro, identidad)
    else:
        m15 = construir_almacenes(root, mercados, "15m", limite, **comun)
        h4 = construir_almacenes(root, mercados, "4h", limite, **comun)
    mercados_ok = tuple(sorted(set(m15) & set(h4)))
    motor = Motor(m15, h4, mercados_ok, led, bootstrap_hasta=bootstrap_hasta)
    # CF-31/CF-34: los huecos LOCALES se emiten por la vía canónica del motor
    # para que lleven heads, commit y processed_at como cualquier otro evento
    # causal (antes se escribían directo al ledger, sin esa provenance).
    #
    # La fuente son los marcadores SELLADOS EN EL ALMACÉN, no los declarados
    # en ESTA corrida: si el proceso murió entre el sellado del gap y su
    # append al ledger, al reiniciar el marcador ya está en el almacén y no
    # vuelve a declararse, así que su evento se perdía para siempre. Recorrer
    # los registros repone todo marcador local, y `event_id` hace que la
    # reemisión sea idempotente.
    motor.iniciar_ciclo()
    try:
        for tf_h, almacenes_tf in (("15m", m15), ("4h", h4)):
            for mercado in mercados_ok:
                for r in almacenes_tf[mercado].registros:
                    if r["tipo"] != "gap" or r.get("motivo") != "local":
                        continue
                    motor._emit("hueco_detectado", r["detected_at"], mercado,
                                finalized_at=r["detected_at"],
                                efectivo=r["desde"], tf=tf_h,
                                desde=r["desde"], hasta=r["hasta"],
                                motivo="local", detected_at=r["detected_at"])
    finally:
        motor.finalizar_ciclo()
    cierres = sorted({int(v["t"]) + DUR_M15
                      for m in mercados_ok for v in m15[m].velas})
    for T in cierres:
        if desde is not None and T < desde:
            continue
        if hasta is not None and T > hasta:
            break
        # CF-34: un ciclo/pull = un reloj observado, compartido por el
        # watermark y por el lote que libera.
        motor.iniciar_ciclo()
        try:
            # CF-29: primero se RESTAURA lo que un marcador exchange ya
            # sellado implica (degradación + eventos), y recién después se
            # evalúa el watermark. En vivo es un no-op.
            motor.recuperar_exchange(T)
            if not motor.lote_finalizable(T):
                # CF-29/CF-23: un mercado silencioso no bloquea para siempre
                # — se intenta el watermark global y se reevalúa.
                motor.watermark_exchange(T)
                if not motor.lote_finalizable(T):
                    continue
            motor.procesar_lote(T)
        finally:
            # Una excepción no puede dejar el ciclo abierto con el reloj
            # retenido (se propagaría a eventos de ciclos posteriores).
            motor.finalizar_ciclo()
        if motor.cortado:
            break
    # CF-35: sin lote global finalizado posterior a T_corte y con el reloj
    # pasado la gracia, el experimento se cierra administrativamente.
    if not motor.cortado and reloj_ms is not None:
        motor.cerrar_administrativo(reloj_ms)
    return motor, led
