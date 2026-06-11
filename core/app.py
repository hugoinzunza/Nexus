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
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles

from core.hub import ROOT, Hub, load_config, log
from core import push

STATIC_DIR = os.path.join(ROOT, "static")

# El hub se crea al importar el módulo (uvicorn importa `core.app:app`). Los
# módulos se arrancan/detienen en el ciclo de vida (lifespan) de FastAPI.
hub = Hub(load_config())


@asynccontextmanager
async def lifespan(app: FastAPI):
    hub.boot()
    push.init(ROOT, log)
    yield
    hub.shutdown()


app = FastAPI(title="Nexus · Hub personal", version="0.2.0", lifespan=lifespan)

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
    return Response(content=_FAVICON, media_type="image/svg+xml")


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


# --- Web push (preparado; las alertas se implementan más adelante) -------
@app.get("/api/push/public-key")
def push_public_key():
    return {"key": push.public_key_b64(), "configurado": push.configurado()}


@app.post("/api/push/subscribe")
async def push_subscribe(request: Request):
    data = await request.json()
    n = push.guardar_suscripcion(data)
    return {"ok": True, "suscripciones": n}


@app.post("/api/push/unsubscribe")
async def push_unsubscribe(request: Request):
    data = await request.json()
    n = push.borrar_suscripcion(data.get("endpoint", ""))
    return {"ok": True, "suscripciones": n}


# --- Módulos -------------------------------------------------------------
@app.get("/m/{slug}/api/{subpath:path}")
def module_api(slug: str, subpath: str, request: Request):
    module = hub.modules_by_slug.get(slug)
    if module is None:
        return JSONResponse({"error": f"módulo '{slug}' no encontrado"}, status_code=404)

    query = dict(request.query_params)

    # Primero intentamos un stream SSE.
    stream = module.sse(subpath, query)
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

    result = module.api(subpath, query)
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

    raw = await request.body()
    try:
        data = __import__("json").loads(raw) if raw else None
    except Exception:  # noqa: BLE001
        data = None
    headers = {k.lower(): v for k, v in request.headers.items()}

    result = module.api_post(subpath, data, headers)
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
def module_static(slug: str, relpath: str):
    module = hub.modules_by_slug.get(slug)
    if module is None:
        return JSONResponse({"error": f"módulo '{slug}' no encontrado"}, status_code=404)

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


# Favicon mínimo en SVG (un nodo morado) para que el navegador no de 404.
_FAVICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<rect width="32" height="32" rx="7" fill="#6c5ce7"/>'
    '<circle cx="16" cy="16" r="5" fill="#fff"/>'
    '<circle cx="6" cy="7" r="2.5" fill="#a29bfe"/>'
    '<circle cx="26" cy="7" r="2.5" fill="#a29bfe"/>'
    '<circle cx="6" cy="25" r="2.5" fill="#a29bfe"/>'
    '<circle cx="26" cy="25" r="2.5" fill="#a29bfe"/>'
    '</svg>'
).encode("utf-8")
