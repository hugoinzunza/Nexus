"""Servidor HTTP del núcleo.

Responsabilidades:
  - Servir la página de inicio del hub (lista de módulos).
  - Enrutar /m/<slug>/... hacia el módulo correspondiente (estáticos + API).
  - Soportar streams SSE para datos en vivo.
  - Exponer /health con el estado del sistema.

Usa solo la librería estándar (http.server) para no depender de nada externo.
Cada petición corre en su propio hilo (ThreadingHTTPServer) para que los
streams SSE de larga duración no bloqueen al resto.
"""

from __future__ import annotations

import json
import mimetypes
import os
import posixpath
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs


class NexusHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, handler_cls, hub):
        super().__init__(addr, handler_cls)
        self.hub = hub  # referencia al Hub para acceder a módulos y config


class NexusRequestHandler(BaseHTTPRequestHandler):
    server_version = "Nexus/0.1"

    # Silenciamos el log por defecto de http.server (muy ruidoso) y usamos
    # el logger del hub solo para errores.
    def log_message(self, fmt, *args):  # noqa: D401
        pass

    @property
    def hub(self):
        return self.server.hub

    # ------------------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        try:
            if path == "/" or path == "":
                return self._send_html(self.hub.render_landing())
            if path == "/health":
                return self._send_json(200, self.hub.health())
            if path == "/favicon.ico":
                return self._send_bytes(200, "image/svg+xml", _FAVICON)
            if path.startswith("/m/"):
                return self._handle_module(path, query)
            return self._send_json(404, {"error": "ruta no encontrada", "path": path})
        except (BrokenPipeError, ConnectionResetError):
            # El cliente cerró la conexión (típico al cerrar un stream SSE).
            return
        except Exception as exc:  # noqa: BLE001
            self.hub.log(f"error sirviendo {path}: {exc}")
            try:
                self._send_json(500, {"error": str(exc)})
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    def _handle_module(self, path: str, query: dict):
        # path = /m/<slug>/<resto>
        rest = path[len("/m/"):]
        if "/" in rest:
            slug, remainder = rest.split("/", 1)
        else:
            slug, remainder = rest, ""

        module = self.hub.modules_by_slug.get(slug)
        if module is None:
            return self._send_json(404, {"error": f"módulo '{slug}' no encontrado"})

        # API del módulo: /m/<slug>/api/<subpath>
        if remainder.startswith("api/") or remainder == "api":
            subpath = remainder[4:] if remainder.startswith("api/") else ""

            # Primero intentamos un stream SSE.
            stream = module.sse(subpath, query)
            if stream is not None:
                return self._stream_sse(stream)

            result = module.api(subpath, query)
            if result is not None:
                status, ctype, body = result
                return self._send_bytes(status, ctype, body)
            return self._send_json(404, {"error": "endpoint de API no encontrado", "subpath": subpath})

        # Archivos estáticos del módulo.
        return self._serve_static(module, remainder)

    # ------------------------------------------------------------------
    def _serve_static(self, module, relpath: str):
        public = module.public_dir()
        if not public:
            return self._send_json(404, {"error": "el módulo no tiene archivos estáticos"})

        if relpath in ("", "/"):
            relpath = "index.html"

        # Normalizamos para evitar path traversal (../../etc).
        safe = posixpath.normpath("/" + relpath).lstrip("/")
        full = os.path.join(public, safe)
        if not os.path.abspath(full).startswith(os.path.abspath(public)):
            return self._send_json(403, {"error": "ruta no permitida"})
        if not os.path.isfile(full):
            return self._send_json(404, {"error": "archivo no encontrado", "path": relpath})

        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as fh:
            self._send_bytes(200, ctype, fh.read())

    # ------------------------------------------------------------------
    def _stream_sse(self, generator):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            for chunk in generator:
                if chunk is None:
                    continue
                self.wfile.write(chunk.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            close = getattr(generator, "close", None)
            if close:
                close()

    # --- Helpers de respuesta -----------------------------------------
    def _send_bytes(self, status: int, content_type: str, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, obj):
        self._send_bytes(status, "application/json; charset=utf-8",
                         json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _send_html(self, html: str):
        self._send_bytes(200, "text/html; charset=utf-8", html.encode("utf-8"))


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
