"""Módulo nativo headless del NEXUX Command Center."""

from __future__ import annotations

import copy
import json

from core.hub import load_config
from core.module_base import NexusModule

from .contracts import (
    CONTRACT_V1_FINGERPRINT,
    CONTRACT_V1_SPEC,
    CONTRACT_VERSION,
    SNAPSHOT_CONTRACT,
)
from .snapshot import (
    ConfiguredModulesProjection,
    SessionProjection,
    SnapshotComposer,
)


class CommandCenterModule(NexusModule):
    slug = "command-center"
    title = "Command Center"
    description = "Infraestructura headless de conciencia situacional."
    icon = "CC"

    def __init__(self, context):
        super().__init__(context)
        self._composer = SnapshotComposer(
            [SessionProjection(), ConfiguredModulesProjection(load_config)]
        )

    @staticmethod
    def _json(status: int, payload: dict):
        body = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        return status, "application/json", body

    def api(self, subpath: str, query: dict, user=None):
        if subpath == "contract/v1":
            return self._json(200, {
                "contract": SNAPSHOT_CONTRACT,
                "v": CONTRACT_VERSION,
                "fingerprint": CONTRACT_V1_FINGERPRINT,
                "spec": copy.deepcopy(CONTRACT_V1_SPEC),
            })
        if subpath != "snapshot":
            return None
        if not user:
            return self._json(401, {"error": "no autorizado"})
        try:
            return self._json(200, self._composer.compose(user))
        except ValueError:
            return self._json(401, {"error": "sesion sin identidad estable"})

    def health(self) -> dict:
        return {
            "slug": self.slug,
            "status": "ok",
            "contract_version": 1,
            "surface": "headless",
        }


def get_module(context):
    return CommandCenterModule(context)
