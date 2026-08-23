"""Servidor web de Nexus — FastAPI + uvicorn.

Reemplaza al viejo núcleo basado en http.server. Responsabilidades:

  - Servir la página de inicio del hub (lista de módulos).
  - Enrutar /m/<slug>/... hacia el módulo correspondiente (estáticos + API).
  - Soportar streams SSE para datos en vivo (StreamingResponse).
  - Exponer /health con el estado del sistema.
  - Servir los recursos de la PWA (manifest, service worker, íconos).
  - Dejar preparado el web push para alertas futuras (ver core/push.py).

El contrato de los módulos (core/module_base.py) no cambió: cada módulo sigue
exponiendo public_dir(), api(subpath, query) y sse(subpath, query). Acá solo
traducimos esas piezas al mundo FastAPI.

Se ejecuta con:  uvicorn core.app:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations

import mimetypes
import os
import posixpath
import urllib.parse
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles

from core.hub import ROOT, Hub, load_config, log
from core import push
from core import auth

STATIC_DIR = os.path.join(ROOT, "static")

# El hub se crea al importar el módulo (uvicorn importa `core.app:app`). Los
# módulos se arrancan/detienen en el ciclo de vida (lifespan) de FastAPI.
hub = Hub(load_config())


def _run_db_migrations():
    """Si hay DATABASE_URL (Railway/web), aplica las migraciones de Alembic al
    arrancar (idempotente). Sin DB (VPS/motor, local), no hace nada."""
    from core import db
    if not db.database_enabled():
        return
    try:
        from alembic import command
        from alembic.config import Config
        cfg = Config(os.path.join(ROOT, "alembic.ini"))
        cfg.set_main_option("script_location", os.path.join(ROOT, "migrations"))
        command.upgrade(cfg, "head")
        log("db: migraciones aplicadas (alembic upgrade head)")
    except Exception as exc:  # noqa: BLE001
        # Fallar el arranque a propósito: es preferible un deploy caído y visible
        # (Railway reintenta) que servir con un esquema de DB desfasado en silencio.
        log(f"db: FALLO al migrar, abortando arranque: {exc}")
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    _run_db_migrations()
    hub.boot()
    push.init(ROOT, log)
    yield
    hub.shutdown()


app = FastAPI(title="NexUX · Hub personal", version="0.2.0", lifespan=lifespan)

# Recursos estáticos compartidos de la PWA (manifest, sw, íconos, pwa.js).
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# --- Núcleo --------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def landing():
    return HTMLResponse(hub.render_landing(),
                        headers={"Cache-Control": "no-cache, must-revalidate"})


@app.get("/health")
def health():
    return JSONResponse(hub.health())


@app.get("/favicon.ico")
def favicon():
    with open(_FAVICON_PATH, "rb") as fh:
        return Response(content=fh.read(), media_type="image/x-icon",
                        headers={"Cache-Control": "public, max-age=86400"})


@app.get("/manifest.webmanifest")
def manifest():
    path = os.path.join(STATIC_DIR, "manifest.webmanifest")
    with open(path, "rb") as fh:
        return Response(content=fh.read(), media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    # El service worker se sirve desde la raíz para que su "scope" cubra todo
    # el sitio (un SW en /static/ solo controlaría /static/).
    path = os.path.join(STATIC_DIR, "sw.js")
    with open(path, "rb") as fh:
        return Response(content=fh.read(), media_type="text/javascript",
                        headers={"Cache-Control": "no-cache"})


# --- Previews de diseño (mockups; se quitan al integrarse al producto) ---
@app.get("/preview/{name}", response_class=HTMLResponse)
def design_preview(name: str):
    # Whitelist (sin path traversal): solo los mockups del rediseño.
    if name not in ("landing", "home", "home-public", "home-clean", "isotipo"):
        return HTMLResponse("preview no encontrado", status_code=404)
    path = os.path.join(ROOT, "docs", "diseno", f"{name}.html")
    if not os.path.isfile(path):
        return HTMLResponse("preview no encontrado", status_code=404)
    with open(path, "r", encoding="utf-8") as fh:
        return HTMLResponse(fh.read())


# --- Legal (términos + privacidad + disclaimer "no es asesoría") ---------
@app.get("/legal", response_class=HTMLResponse)
def legal():
    path = os.path.join(ROOT, "core", "legal.html")
    with open(path, "r", encoding="utf-8") as fh:
        return HTMLResponse(fh.read(), headers={"Cache-Control": "no-cache"})


# --- Web push (preparado; las alertas se implementan más adelante) -------
@app.get("/api/push/public-key")
def push_public_key():
    return {"key": push.public_key_b64(), "configurado": push.configurado()}


def _push_gate(request: Request):
    """Las alertas hoy contienen datos de Hugo (bot real + su forward-test), así que
    SOLO admin se suscribe. Antes era público → cualquiera recibía sus alertas de
    trading real. (Auth inerte/local = single-user → se permite.)"""
    if auth.enabled() and not auth.is_admin(auth.current_user(request)):
        return JSONResponse({"error": "solo administradores"}, status_code=403)
    return None


@app.post("/api/push/subscribe")
async def push_subscribe(request: Request):
    blocked = _push_gate(request)
    if blocked is not None:
        return blocked
    data = await request.json()
    n = push.guardar_suscripcion(data)
    return {"ok": True, "suscripciones": n}


@app.post("/api/push/unsubscribe")
async def push_unsubscribe(request: Request):
    blocked = _push_gate(request)
    if blocked is not None:
        return blocked
    data = await request.json()
    n = push.borrar_suscripcion(data.get("endpoint", ""))
    return {"ok": True, "suscripciones": n}


@app.post("/api/push/test")
async def push_test(request: Request):
    """Dispara una notificación de PRUEBA a las suscripciones. Auth con
    NEXUS_INGEST_TOKEN (header X-Nexus-Token) para no dejarlo abierto."""
    import hmac
    token = os.environ.get("NEXUS_INGEST_TOKEN", "").strip()
    provided = request.headers.get("x-nexus-token", "")
    if not token or not hmac.compare_digest(str(provided), str(token)):
        return JSONResponse({"error": "no autorizado"}, status_code=401)
    enviados, errores = push.notificar(
        title="🔔 NexUX · prueba",
        body="Si ves esto, las alertas SMC funcionan. (mensaje de prueba)",
        url="/m/trading/", tag="nexus-test")
    from core.paths import persist_dir
    return {"ok": True, "enviados": enviados, "errores": errores,
            "suscripciones": len(push._read_all()),
            "volumen": os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "(NO montado)"),
            "persist_dir": persist_dir(ROOT)}


# --- Auth (Google OAuth2) -----------------------------------------------
# Inerte hasta configurar GOOGLE_CLIENT_ID/SECRET + SESSION_SECRET. Sin eso, el
# sitio funciona como hoy (un usuario, todo abierto).
def _base_url(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


@app.get("/me")
def whoami(request: Request):
    u = auth.current_user(request)
    if not u:
        return JSONResponse({"auth": True, "user": None})
    return {"auth": auth.enabled(), "user": {
        "email": u.get("email"), "name": u.get("name"),
        "role": u.get("role"), "picture": u.get("picture")}}


ACCOUNT_PAGE = os.path.join(ROOT, "core", "account.html")
INICIO_PAGE = os.path.join(ROOT, "core", "inicio.html")

# Destino por defecto tras iniciar sesión.
HOME = "/inicio"


def _safe_next(destino: str | None) -> str:
    """Devuelve `destino` sólo si es una ruta interna; si no, la casa.

    `startswith("/")` no basta: `//evil.example` es una URL protocolo-relativa
    y el navegador la resuelve como host externo (open redirect). También se
    rechazan la barra invertida —que algunos navegadores normalizan a `/`— y
    cualquier cosa que urlparse lea como esquema o netloc.
    """
    if not isinstance(destino, str) or not destino.startswith("/"):
        return HOME
    if destino.startswith("//") or destino.startswith("/\\"):
        return HOME
    partes = urllib.parse.urlsplit(destino)
    if partes.scheme or partes.netloc:
        return HOME
    return destino


@app.get("/inicio", response_class=HTMLResponse)
def inicio_page(request: Request):
    """Selector de mundo tras iniciar sesión: cripto o acciones chilenas.

    `/` sigue siendo la portada pública de marketing; esta es la casa del
    usuario ya autenticado, y el destino por defecto del login."""
    if auth.enabled() and not auth.current_user(request):
        return RedirectResponse(url="/login?next=/inicio", status_code=307)
    with open(INICIO_PAGE, "r", encoding="utf-8") as fh:
        return HTMLResponse(fh.read(), headers={"Cache-Control": "no-cache"})


@app.get("/account", response_class=HTMLResponse)
def account_page(request: Request):
    if auth.enabled() and not auth.current_user(request):
        return RedirectResponse(url="/login?next=/account", status_code=307)
    with open(ACCOUNT_PAGE, "r", encoding="utf-8") as fh:
        return HTMLResponse(fh.read(), headers={"Cache-Control": "no-cache"})


@app.put("/api/account/profile")
async def account_update_profile(request: Request):
    user = auth.current_user(request)
    if not user:
        return JSONResponse({"error": "necesitas iniciar sesión"}, status_code=401)
    if not auth.enabled() or user.get("uid") is None:
        return JSONResponse({"error": "perfil local no editable"}, status_code=409)
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": "payload JSON inválido"}, status_code=400)
    name = " ".join(str((data or {}).get("name") or "").strip().split())
    if not name or len(name) > 120:
        return JSONResponse({"error": "el nombre debe tener entre 1 y 120 caracteres"},
                            status_code=400)
    updated = auth.update_profile(int(user["uid"]), name)
    if not updated:
        return JSONResponse({"error": "usuario no encontrado"}, status_code=404)
    response = JSONResponse({"ok": True, "user": {
        "email": updated["email"], "name": updated["name"],
        "role": updated["role"], "picture": updated["picture"]}})
    response.set_cookie(auth.COOKIE, auth.make_cookie(updated), max_age=60 * 60 * 24 * 7,
                        httponly=True, secure=True, samesite="lax", path="/")
    return response


LOGIN_PAGE = os.path.join(ROOT, "core", "login.html")


@app.get("/login", response_class=HTMLResponse)
def login(request: Request, next: str = "/inicio"):
    # Auth inerte → no hay nada que loguear: a la portada.
    if not auth.enabled():
        return RedirectResponse(url="/", status_code=307)
    # Ya con sesión → directo a su destino (no mostramos el login de nuevo).
    if auth.current_user(request):
        dest = _safe_next(next)
        return RedirectResponse(url=dest, status_code=307)
    # Sin sesión → pantalla de acceso branded (el botón salta a /auth/google).
    with open(LOGIN_PAGE, "r", encoding="utf-8") as fh:
        return HTMLResponse(fh.read(), headers={"Cache-Control": "no-cache"})


@app.get("/auth/google")
def auth_google(request: Request, next: str = "/inicio"):
    """Inicia el flujo OAuth con Google (lo que antes hacía /login directo)."""
    if not auth.enabled():
        return RedirectResponse(url="/", status_code=307)
    cb = auth.redirect_uri(_base_url(request))
    state = auth.sign_state({"next": next})
    return RedirectResponse(url=auth.login_url(state, cb), status_code=307)


@app.get("/auth/callback")
def auth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if not auth.enabled():
        return RedirectResponse(url="/", status_code=307)
    if error or not code:
        return RedirectResponse(url="/login?e=error", status_code=307)
    st = auth.read_state(state)
    if st is None:
        return RedirectResponse(url="/login?e=state", status_code=307)
    cb = auth.redirect_uri(_base_url(request))
    try:
        info = auth.exchange_code(code, cb)
    except Exception as exc:  # noqa: BLE001
        log(f"auth: fallo al intercambiar code: {exc}")
        return RedirectResponse(url="/login?e=error", status_code=307)
    if not info.get("email_verified") or not auth.is_allowed(info.get("email", "")):
        return RedirectResponse(url="/login?e=denied", status_code=307)
    user = auth.upsert_user(info)
    nxt = _safe_next(st.get("next"))   # solo rutas internas (anti open-redirect)
    resp = RedirectResponse(url=nxt, status_code=307)
    resp.set_cookie(auth.COOKIE, auth.make_cookie(user), max_age=60 * 60 * 24 * 30,
                    httponly=True, secure=True, samesite="lax", path="/")
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse(url="/", status_code=307)
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp


# --- Panel de administración (solo admin, solo con auth activa) -----------
ADMIN_PAGE = os.path.join(ROOT, "core", "admin.html")


def _require_admin(request: Request):
    """None si es admin con auth activa; si no, la Response de rechazo.
    Con auth INERTE el panel NO está disponible (evita admin público)."""
    if not auth.enabled():
        return JSONResponse({"error": "el panel de admin requiere el login configurado"},
                            status_code=404)
    if not auth.is_admin(auth.current_user(request)):
        return JSONResponse({"error": "solo administradores"}, status_code=403)
    return None


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    if not auth.enabled():
        return RedirectResponse(url="/", status_code=307)
    if not auth.is_admin(auth.current_user(request)):
        return RedirectResponse(url="/login?next=/admin", status_code=307)
    with open(ADMIN_PAGE, "r", encoding="utf-8") as fh:
        return HTMLResponse(fh.read(), headers={"Cache-Control": "no-cache"})


@app.get("/api/admin/invitations")
def admin_list_invitations(request: Request):
    blocked = _require_admin(request)
    if blocked is not None:
        return blocked
    return {"invitations": auth.list_invitations()}


@app.post("/api/admin/invitations")
async def admin_add_invitation(request: Request):
    blocked = _require_admin(request)
    if blocked is not None:
        return blocked
    data = await request.json()
    me = auth.current_user(request)
    res = auth.add_invitation((data or {}).get("email", ""), me.get("uid") if me else None)
    return JSONResponse(res, status_code=200 if res.get("ok") else 400)


@app.delete("/api/admin/invitations/{inv_id}")
def admin_delete_invitation(inv_id: int, request: Request):
    blocked = _require_admin(request)
    if blocked is not None:
        return blocked
    return {"ok": auth.delete_invitation(inv_id)}


@app.get("/api/admin/users")
def admin_list_users(request: Request):
    blocked = _require_admin(request)
    if blocked is not None:
        return blocked
    return {"users": auth.list_users()}


@app.patch("/api/admin/users/{user_id}/role")
async def admin_set_user_role(user_id: int, request: Request):
    blocked = _require_admin(request)
    if blocked is not None:
        return blocked
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": "payload JSON inválido"}, status_code=400)
    me = auth.current_user(request)
    result = auth.set_user_role(user_id, str((data or {}).get("role") or ""),
                                me.get("uid") if me else None)
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


# Slugs que exigen sesión iniciada (datos personales). El resto es público.
_LOGIN_REQUIRED = {"journal", "coinsignals", "coinglass", "hypothesis-lab", "acciones_chile"}
_ADMIN_REQUIRED = {"bot"}
# Tope duro del cuerpo de CUALQUIER POST de modulo, aplicado antes de leerlo.
# Es holgado a proposito: el snapshot visual de CoinGlass ronda los 40 KB y el mas
# grande que ingesta el proyecto (CoinSignals) declara 4 MB. 8 MB deja margen sin
# permitir que alguien sin sesion haga bufferizar cientos de MB.
MAX_POST_BYTES = 8_000_000

_TOKEN_AUTH_POSTS = {
    ("bot", "ingest"),
    ("coinglass", "ingest"),
    ("coinglass", "visual-ingest"),
    ("coinsignals", "ingest"),
    ("inteligencia", "klines-ingest"),
    ("journal", "ingest"),
    ("journal", "ingest_setups"),
    ("journal", "connections"),
    ("journal", "connection-status"),
    ("journal", "vault-check"),
    ("acciones_chile", "ingest-telegram-events"),
}


def _gate(slug: str, request: Request):
    """Devuelve una Response si hay que bloquear/redirigir; None si pasa."""
    if not auth.enabled():
        return None
    user = auth.current_user(request)
    requires_login = slug in _LOGIN_REQUIRED or slug in _ADMIN_REQUIRED
    if not requires_login:
        return None
    is_api = request.url.path.startswith(f"/m/{slug}/api/")
    if user is None:
        if is_api:
            return JSONResponse({"error": "no autorizado", "login": "/login"}, status_code=401)
        nxt = request.url.path
        return RedirectResponse(url=f"/login?next={nxt}", status_code=307)
    if slug in _ADMIN_REQUIRED and not auth.is_admin(user):
        if is_api:
            return JSONResponse({"error": "solo administradores"}, status_code=403)
        return RedirectResponse(url="/inicio", status_code=307)
    return None


# --- Módulos -------------------------------------------------------------
@app.get("/m/{slug}/api/{subpath:path}")
def module_api(slug: str, subpath: str, request: Request):
    module = hub.modules_by_slug.get(slug)
    if module is None:
        return JSONResponse({"error": f"módulo '{slug}' no encontrado"}, status_code=404)

    blocked = _gate(slug, request)
    if blocked is not None:
        return blocked

    query = dict(request.query_params)
    user = auth.current_user(request)

    # Primero intentamos un stream SSE.
    stream = module.sse(subpath, query, user=user)
    if stream is not None:
        return StreamingResponse(
            stream,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    result = module.api(subpath, query, user=user)
    if result is not None:
        status, ctype, body = result
        return Response(content=body, status_code=status, media_type=ctype)
    return JSONResponse({"error": "endpoint de API no encontrado", "subpath": subpath},
                        status_code=404)


@app.post("/m/{slug}/api/{subpath:path}")
async def module_api_post(slug: str, subpath: str, request: Request):
    module = hub.modules_by_slug.get(slug)
    if module is None:
        return JSONResponse({"error": f"módulo '{slug}' no encontrado"}, status_code=404)

    # Las ingestas del colector usan X-Nexus-Token y se validan dentro del módulo.
    # El resto de POSTs de módulos privados sí exige la sesión del navegador.
    if (slug, subpath) not in _TOKEN_AUTH_POSTS:
        blocked = _gate(slug, request)
        if blocked is not None:
            return blocked

    # El tope se aplica ANTES de leer y parsear, no después.
    #
    # Los módulos tenían su propio límite (`MAX_BODY`), pero recién lo miraban dentro
    # de `api_post`, o sea con el cuerpo entero ya en memoria y ya deserializado. Y
    # las rutas de ingesta se saltan `_gate`, así que cualquiera sin sesión podía
    # hacer que el servidor bufferizara y parseara lo que quisiera antes de que nadie
    # mirara el token (auditoría 2026-07-26).
    #
    # Verificado el 2026-07-26: uvicorn 0.32 con h11 NO trae límite de cuerpo por
    # defecto y no hay ninguno configurado en el deploy, así que nada corta aguas
    # arriba. El de acá es el primero.
    largo = request.headers.get("content-length")
    if largo is not None:
        try:
            if int(largo) > MAX_POST_BYTES:
                return JSONResponse({"error": "cuerpo demasiado grande"}, status_code=413)
        except ValueError:
            return JSONResponse({"error": "content-length invalido"}, status_code=400)
    # Sin `content-length` (transfer-encoding: chunked) el header no sirve de nada, así
    # que se lee por trozos y se corta apenas se pasa. Confiar en el header declarado
    # sería dejar la puerta abierta justo al que miente.
    trozos, total = [], 0
    async for trozo in request.stream():
        total += len(trozo)
        if total > MAX_POST_BYTES:
            return JSONResponse({"error": "cuerpo demasiado grande"}, status_code=413)
        trozos.append(trozo)
    raw = b"".join(trozos)
    try:
        data = __import__("json").loads(raw) if raw else None
    except Exception:  # noqa: BLE001
        data = None
    headers = {k.lower(): v for k, v in request.headers.items()}
    user = auth.current_user(request)

    result = module.api_post(subpath, data, headers, user=user)
    if result is not None:
        status, ctype, body = result
        return Response(content=body, status_code=status, media_type=ctype)
    return JSONResponse({"error": "endpoint de API no encontrado", "subpath": subpath},
                        status_code=404)


@app.get("/m/{slug}")
def module_root_redirect(slug: str):
    # /m/trading → /m/trading/ (para que los enlaces relativos del módulo funcionen).
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"/m/{slug}/", status_code=307)


@app.get("/m/{slug}/{relpath:path}")
def module_static(slug: str, relpath: str, request: Request):
    module = hub.modules_by_slug.get(slug)
    if module is None:
        return JSONResponse({"error": f"módulo '{slug}' no encontrado"}, status_code=404)

    blocked = _gate(slug, request)
    if blocked is not None:
        return blocked

    public = module.public_dir()
    if not public:
        return JSONResponse({"error": "el módulo no tiene archivos estáticos"}, status_code=404)

    if relpath in ("", "/"):
        relpath = "index.html"

    # Normalizamos para evitar path traversal (../../etc).
    safe = posixpath.normpath("/" + relpath).lstrip("/")
    full = os.path.join(public, safe)
    if not os.path.abspath(full).startswith(os.path.abspath(public)):
        return JSONResponse({"error": "ruta no permitida"}, status_code=403)
    # URLs limpias: /m/trading/backtest → backtest.html si no existe el exacto.
    if not os.path.isfile(full) and os.path.isfile(full + ".html"):
        full = full + ".html"
    if not os.path.isfile(full):
        return JSONResponse({"error": "archivo no encontrado", "path": relpath}, status_code=404)

    ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
    with open(full, "rb") as fh:
        # HTML/JS/CSS de los módulos: no-cache para que el navegador (y la PWA del
        # iPhone) siempre revalide y tome la versión nueva apenas se despliega.
        headers = {}
        if full.endswith((".html", ".js", ".css", ".webmanifest")):
            headers["Cache-Control"] = "no-cache, must-revalidate"
        return Response(content=fh.read(), media_type=ctype, headers=headers)


# Fallback para navegadores que solicitan /favicon.ico aunque la página declare
# el PNG explícito. Servimos el mismo isotipo en formato compatible.
_FAVICON_PATH = os.path.join(STATIC_DIR, "icons", "nexux-favicon-v5.ico")
