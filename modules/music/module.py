"""Módulo de música — placeholder.

Todavía no hace nada funcional; existe para (1) reservar el espacio dentro de
la visión de Nexus y (2) servir de plantilla mínima de cómo luce un módulo.

Ideas futuras: integrar Spotify/Apple Music, biblioteca local, análisis de
escuchas, recomendaciones, control del audio del Mac mini, etc.
"""

from __future__ import annotations

from core.module_base import NexusModule


class MusicModule(NexusModule):
    slug = "music"
    title = "Música"
    description = "Próximamente: tu centro musical (biblioteca, reproducción y análisis)."
    icon = "🎵"


def get_module(context):
    return MusicModule(context)
