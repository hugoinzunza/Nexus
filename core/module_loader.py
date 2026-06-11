"""Descubre y carga los módulos declarados en la configuración.

Recorre `config.modules`, y por cada módulo habilitado importa
`modules/<slug>/module.py` y llama a su función `get_module(context)`.
"""

from __future__ import annotations

import importlib
import os
from typing import List

from .module_base import ModuleContext, NexusModule


def load_modules(modules_root: str, config: dict, log) -> List[NexusModule]:
    """Devuelve la lista de módulos listos para arrancar."""
    loaded: List[NexusModule] = []
    modules_cfg = config.get("modules", {})

    for slug, mod_cfg in modules_cfg.items():
        if not mod_cfg.get("enabled", True):
            log(f"módulo '{slug}' deshabilitado en config, se omite")
            continue

        module_dir = os.path.join(modules_root, slug)
        if not os.path.isdir(module_dir):
            log(f"⚠️  módulo '{slug}' declarado en config pero no existe la carpeta {module_dir}")
            continue

        try:
            py_module = importlib.import_module(f"modules.{slug}.module")
        except Exception as exc:  # noqa: BLE001 - queremos seguir con los demás
            log(f"⚠️  no se pudo importar el módulo '{slug}': {exc}")
            continue

        if not hasattr(py_module, "get_module"):
            log(f"⚠️  el módulo '{slug}' no define get_module(context), se omite")
            continue

        context = ModuleContext(slug=slug, module_dir=module_dir, module_config=mod_cfg, log=log)
        try:
            instance = py_module.get_module(context)
            instance.slug = instance.slug or slug
            loaded.append(instance)
            log(f"✓ módulo cargado: {slug} ({instance.title})")
        except Exception as exc:  # noqa: BLE001
            log(f"⚠️  error al instanciar el módulo '{slug}': {exc}")

    return loaded
