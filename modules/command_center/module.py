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
    error_document,
)
from .chart_provider import CHART_PROVIDER_INTERFACE_VERSION
from .event_bus import InMemoryEventBus
from .gateway import CommandCenterGateway
from .media_controller import MEDIA_CONTROLLER_INTERFACE_VERSION
from .snapshot import (
    ConfiguredModulesProjection,
    IdentityError,
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
        self.event_bus = InMemoryEventBus()
        self._composer = SnapshotComposer(
            [SessionProjection(), ConfiguredModulesProjection(load_config)],
            on_provider_error=self._provider_error,
        )
        self.gateway = CommandCenterGateway(
            self.event_bus,
            self._composer,
            on_error=lambda code: self.context.log(
                f"command-center: gateway {code}"
            ),
        )

    def _provider_error(self, topic: str, exc: Exception) -> None:
        self.context.log(
            f"command-center: provider {topic} degradado ({type(exc).__name__})"
        )

    @staticmethod
    def _json(status: int, payload: dict):
        body = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        return status, "application/json", body

    def api(self, subpath: str, query: dict, user=None):
        if not user:
            return self._json(
                401,
                error_document(
                    "auth.required",
                    "Se requiere una sesion autenticada.",
                    401,
                ),
            )
        if subpath == "contract/v1":
            return self._json(
                200,
                {
                    "status": "frozen",
                    "v": CONTRACT_VERSION,
                    "fingerprint": CONTRACT_V1_FINGERPRINT,
                    "schema": copy.deepcopy(CONTRACT_V1_SPEC),
                },
            )
        if subpath != "snapshot":
            return self._json(
                404,
                error_document(
                    "endpoint.not-found",
                    "El endpoint solicitado no existe.",
                    404,
                ),
            )
        try:
            return self._json(200, self._composer.compose(user))
        except IdentityError:
            return self._json(
                401,
                error_document(
                    "auth.identity-invalid",
                    "La sesion no posee una identidad estable.",
                    401,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            self.context.log(
                f"command-center: snapshot fallo ({type(exc).__name__})"
            )
            return self._json(
                500,
                error_document(
                    "snapshot.compose-failed",
                    "No fue posible construir el snapshot.",
                    500,
                    retryable=True,
                ),
            )

    def health(self) -> dict:
        return {
            "slug": self.slug,
            "status": "ok",
            "contract_version": CONTRACT_VERSION,
            "contract_status": "frozen",
            "event_bus": self.event_bus.stats(),
            "gateway": self.gateway.stats(),
            "interfaces": {
                "chart_provider": {
                    "version": CHART_PROVIDER_INTERFACE_VERSION,
                    "status": "contract-only",
                },
                "media_controller": {
                    "version": MEDIA_CONTROLLER_INTERFACE_VERSION,
                    "status": "contract-only",
                },
            },
            "surface": "headless",
        }

    async def websocket(self, peer, user_loader) -> None:
        await self.gateway.handle(peer, user_loader)


def get_module(context):
    return CommandCenterModule(context)
