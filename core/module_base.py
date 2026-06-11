"""Contrato base de un módulo de Nexus.

Un módulo es una pieza enchufable que el núcleo descubre, arranca y expone en
la web. Para crear uno nuevo basta con:

  1. Crear una carpeta en `modules/<slug>/`.
  2. Poner ahí un `module.py` con una función `get_module(context)` que
     devuelva una instancia de una subclase de `NexusModule`.
  3. (Opcional) Poner archivos estáticos en `modules/<slug>/public/`.

El núcleo se encarga del routing, los archivos estáticos y el ciclo de vida.
El módulo solo decide qué datos sirve.
"""

from __future__ import annotations

import os
from typing import Optional, Tuple


class NexusModule:
    """Clase base que todos los módulos extienden.

    Atributos que cada módulo debe definir:
      slug         -> identificador en la URL (ej: "trading" => /m/trading/)
      title        -> nombre legible para mostrar en el hub
      description  -> descripción corta para la tarjeta del hub
      icon         -> emoji o símbolo que representa al módulo
    """

    slug: str = ""
    title: str = "Módulo sin nombre"
    description: str = ""
    icon: str = "📦"

    def __init__(self, context: "ModuleContext"):
        self.context = context
        self.config = context.module_config

    # --- Ciclo de vida -------------------------------------------------
    def start(self) -> None:
        """Se llama una vez cuando el hub arranca. Ideal para lanzar hilos
        de fondo (por ejemplo, el poller de datos de mercado)."""

    def stop(self) -> None:
        """Se llama cuando el hub se apaga. Ideal para cerrar recursos."""

    # --- Contenido -----------------------------------------------------
    def public_dir(self) -> Optional[str]:
        """Carpeta de archivos estáticos. Por convención `public/` dentro
        de la carpeta del módulo. El núcleo la sirve en /m/<slug>/."""
        guess = os.path.join(self.context.module_dir, "public")
        return guess if os.path.isdir(guess) else None

    def api(self, subpath: str, query: dict) -> Optional[Tuple[int, str, bytes]]:
        """Maneja peticiones GET a /m/<slug>/api/<subpath>.

        Devuelve una tupla (status, content_type, body_bytes) o None si la
        ruta no existe (el núcleo responderá 404).
        """
        return None

    def api_post(self, subpath: str, body, headers: dict) -> Optional[Tuple[int, str, bytes]]:
        """Maneja peticiones POST a /m/<slug>/api/<subpath>.

        `body` es el JSON ya parseado (o None si no vino o no era JSON válido).
        `headers` es un dict con las cabeceras (claves en minúscula). Devuelve
        (status, content_type, body_bytes) o None si la ruta no existe.
        """
        return None

    def sse(self, subpath: str, query: dict):
        """Maneja un stream Server-Sent Events en /m/<slug>/api/<subpath>.

        Debe devolver un generador que produzca strings ya formateados como
        eventos SSE (ej: "data: {...}\\n\\n"), o None si no aplica.
        """
        return None

    def health(self) -> dict:
        """Estado del módulo para el endpoint /health del núcleo."""
        return {"slug": self.slug, "status": "ok"}


class ModuleContext:
    """Todo lo que un módulo necesita del entorno: su configuración, su
    carpeta en disco y el logger compartido."""

    def __init__(self, slug: str, module_dir: str, module_config: dict, log):
        self.slug = slug
        self.module_dir = module_dir
        self.module_config = module_config
        self.log = log
