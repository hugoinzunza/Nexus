"""Directorio para estado que debe SOBREVIVIR a los deploys.

En Railway el `data/` del repo es efímero (se reescribe en cada deploy), así que las
suscripciones push y las ingestas del colector se perderían. Si hay un VOLUMEN
montado (Railway expone RAILWAY_VOLUME_MOUNT_PATH), se usa ese; en el Mac mini /
local cae a <root>/data (continuo, ya persistente).

Ojo: la historia de velas (klines_*.json) NO usa esto — va versionada en git y se
lee del repo. Esto es solo para estado de runtime (push_subs, *_ingest).
"""
from __future__ import annotations

import os


def persist_dir(root: str) -> str:
    vol = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
    d = vol or os.path.join(root, "data")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d
