"""Módulo nativo headless del NEXUX Command Center."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import threading
import time

from core.hub import load_config
from core.module_base import NexusModule

from .contracts import (
    CONTRACT_V1_FINGERPRINT,
    CONTRACT_V1_SPEC,
    CONTRACT_VERSION,
    error_document,
)
from .chart_provider import CHART_PROVIDER_INTERFACE_VERSION
from .ai_context import AiContextService
from .apple_music_adapter import AppleMusicAdapter
from .bot_context import BotContextService
from .event_bus import InMemoryEventBus
from .external_artwork import ExternalArtworkResolver
from .gateway import CommandCenterGateway
from .media_controller import MEDIA_CONTROLLER_INTERFACE_VERSION, MediaAction
from .media_surface import MediaCommandsDisabled, MediaSurfaceService
from .market_ribbon import MarketRibbonService
from .module_registry import command_center_module_registry
from .operations import OperationContext
from .positions_context import PositionsContextService
from .qobuz_adapter import QobuzAdapter
from .snapshot import (
    ConfiguredModulesProjection,
    IdentityError,
    SessionProjection,
    SnapshotComposer,
)
from .tidal_adapter import TidalAdapter

_MEDIA_PROVIDERS = ("apple-music", "qobuz", "tidal")


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
        self.module_registry = command_center_module_registry()
        self.market_ribbon = MarketRibbonService()
        self.ai_context = AiContextService(
            enabled_loader=self._ai_enabled,
        )
        self.bot_context = BotContextService()
        self.positions_context = PositionsContextService()
        self._local_media_enabled = os.environ.get(
            "NEXUX_COMMAND_CENTER_MEDIA"
        ) in {"apple-music", "local"}
        self._external_artwork = (
            ExternalArtworkResolver() if self._local_media_enabled else None
        )
        self._apple_music = (
            AppleMusicAdapter() if self._local_media_enabled else None
        )
        controllers = {
            "apple-music": self._apple_music,
            "qobuz": QobuzAdapter() if self._local_media_enabled else None,
            "tidal": TidalAdapter() if self._local_media_enabled else None,
        }
        self._qobuz = controllers["qobuz"]
        self._tidal = controllers["tidal"]
        self._media_selection_lock = threading.Lock()
        self._media_snapshot_locks = {
            provider: threading.Lock() for provider in _MEDIA_PROVIDERS
        }
        self._media_snapshot_cache: dict[str, tuple[float, dict]] = {}
        self._media_snapshot_ttl_seconds = 2.5
        self._media_last_playback = {
            provider: "unknown" for provider in _MEDIA_PROVIDERS
        }
        self._active_media_provider: str | None = None
        self.media_surfaces = {
            provider: MediaSurfaceService(
                controller,
                commands_enabled=controller is not None,
                metadata_resolver=(
                    lambda item_ref, selected=provider: self._media_metadata(
                        selected, item_ref
                    )
                    if controller is not None
                    else None
                ),
                timeout_seconds=7.0 if provider == "qobuz" else 4.0,
            )
            for provider, controller in controllers.items()
        }
        # Compatibilidad para consumidores internos anteriores a la selección.
        self.media_surface = self.media_surfaces["apple-music"]

    def _media_metadata(self, provider: str, item_ref: str) -> dict | None:
        controller = {
            "apple-music": self._apple_music,
            "qobuz": self._qobuz,
            "tidal": self._tidal,
        }.get(provider)
        metadata = getattr(controller, "metadata", None)
        if not callable(metadata):
            return None
        source = metadata(item_ref)
        if not source:
            return None
        result = dict(source)
        if provider == "apple-music" and result.pop("has_artwork", False):
            version = hashlib.sha256(item_ref.encode("utf-8")).hexdigest()[:16]
            result["artwork_url"] = (
                "/m/command-center/api/media-artwork?v=" + version
            )
        elif provider in {"qobuz", "tidal"} and self._external_artwork:
            artwork_url = self._external_artwork.resolve_cached_or_schedule(
                provider=provider,
                item_ref=item_ref,
                track=str(result.get("track") or ""),
                artist=str(result.get("artist") or ""),
                album=str(result.get("album") or "") or None,
            )
            if artwork_url:
                result["artwork_url"] = artwork_url
        result.pop("item_ref", None)
        return result

    def _media_surface_for(self, provider: str):
        surfaces = getattr(self, "media_surfaces", None)
        if isinstance(surfaces, dict):
            return surfaces.get(provider)
        if provider == "apple-music":
            return getattr(self, "media_surface", None)
        return None

    def _cached_media_snapshot_sync(
        self,
        provider: str,
        *,
        force: bool = False,
    ) -> dict:
        locks = getattr(self, "_media_snapshot_locks", None)
        if not isinstance(locks, dict):
            locks = {
                item: threading.Lock() for item in _MEDIA_PROVIDERS
            }
            self._media_snapshot_locks = locks
        lock = locks.setdefault(provider, threading.Lock())
        with lock:
            cache = getattr(self, "_media_snapshot_cache", None)
            if not isinstance(cache, dict):
                cache = {}
                self._media_snapshot_cache = cache
            now = time.monotonic()
            cached = cache.get(provider)
            ttl = getattr(self, "_media_snapshot_ttl_seconds", 2.5)
            if (
                not force
                and cached is not None
                and now - cached[0] <= ttl
            ):
                return copy.deepcopy(cached[1])
            surface = self._media_surface_for(provider)
            if surface is None:
                raise LookupError("media provider unavailable")
            snapshot = asyncio.run(surface.snapshot())
            cache[provider] = (time.monotonic(), copy.deepcopy(snapshot))
            return snapshot

    async def _cached_media_snapshot(self, provider: str) -> dict:
        return await asyncio.to_thread(
            self._cached_media_snapshot_sync,
            provider,
        )

    def _invalidate_media_snapshot(self, provider: str) -> None:
        cache = getattr(self, "_media_snapshot_cache", None)
        if isinstance(cache, dict):
            cache.pop(provider, None)

    async def _automatic_media_snapshot(self, preferred: str) -> dict:
        snapshots = await asyncio.gather(
            *(self._cached_media_snapshot(provider) for provider in _MEDIA_PROVIDERS),
            return_exceptions=True,
        )
        available = {
            provider: snapshot
            for provider, snapshot in zip(_MEDIA_PROVIDERS, snapshots)
            if isinstance(snapshot, dict)
        }
        if not available:
            raise RuntimeError("no media provider available")

        lock = getattr(self, "_media_selection_lock", None)
        if lock is None:
            lock = threading.Lock()
            self._media_selection_lock = lock
        with lock:
            previous = getattr(self, "_media_last_playback", {})
            playing = [
                provider
                for provider, snapshot in available.items()
                if snapshot.get("playback") == "playing"
            ]
            transitions = [
                provider
                for provider in playing
                if previous.get(provider) != "playing"
            ]
            active = getattr(self, "_active_media_provider", None)
            if transitions:
                selected = (
                    preferred if preferred in transitions else transitions[-1]
                )
            elif active in playing:
                selected = active
            elif preferred in playing:
                selected = preferred
            elif playing:
                selected = playing[0]
            elif preferred in available:
                selected = preferred
            else:
                selected = next(iter(available))
            self._media_last_playback = {
                provider: snapshot.get("playback", "unknown")
                for provider, snapshot in available.items()
            }
            self._active_media_provider = selected if selected in playing else None

        result = dict(available[selected])
        result["selected_provider"] = selected
        result["available_providers"] = list(_MEDIA_PROVIDERS)
        result["selection_mode"] = "automatic"
        return result

    @staticmethod
    def _ai_enabled() -> bool:
        config = load_config()
        trading = (config.get("modules") or {}).get("trading") or {}
        return bool(trading.get("claude_grader_enabled", False))

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
        if subpath == "market-ribbon":
            try:
                return self._json(200, self.market_ribbon.snapshot())
            except Exception as exc:  # noqa: BLE001
                self.context.log(
                    "command-center: market ribbon fallo "
                    f"({type(exc).__name__})"
                )
                return self._json(
                    502,
                    error_document(
                        "market-ribbon.unavailable",
                        "No fue posible obtener el contexto de mercado.",
                        502,
                        retryable=True,
                    ),
                )
        if subpath == "ai-context":
            try:
                return self._json(200, self.ai_context.snapshot())
            except Exception as exc:  # noqa: BLE001
                self.context.log(
                    "command-center: contexto IA fallo "
                    f"({type(exc).__name__})"
                )
                return self._json(
                    502,
                    error_document(
                        "ai-context.unavailable",
                        "No fue posible leer el contexto de IA.",
                        502,
                        retryable=True,
                    ),
                )
        if subpath == "positions-context":
            try:
                from core.app import hub

                journal = hub.modules_by_slug.get("journal")
                bot = hub.modules_by_slug.get("bot")
                if journal is None or bot is None:
                    raise RuntimeError("position sources unavailable")
                journal_response = journal.api("stats", {}, user=user)
                bot_response = bot.api("state", {}, user=user)
                journal_payload = self._module_json_payload(journal_response)
                bot_payload = self._module_json_payload(
                    bot_response,
                    allow_forbidden=True,
                )
                return self._json(
                    200,
                    self.positions_context.project(
                        journal_payload,
                        bot_payload,
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                self.context.log(
                    "command-center: posiciones Binance fallo "
                    f"({type(exc).__name__})"
                )
                return self._json(
                    502,
                    error_document(
                        "positions-context.unavailable",
                        "No fue posible leer las posiciones abiertas.",
                        502,
                        retryable=True,
                    ),
                )
        if subpath == "bot-context":
            try:
                from core.app import hub

                bot = hub.modules_by_slug.get("bot")
                if bot is None:
                    raise RuntimeError("bot module unavailable")
                response = bot.api("state", {}, user=user)
                if response is None:
                    raise RuntimeError("bot state unavailable")
                status, _content_type, body = response
                if status in {401, 403}:
                    return self._json(
                        403,
                        error_document(
                            "bot-context.forbidden",
                            "No tienes acceso al estado del Bot.",
                            403,
                        ),
                    )
                if status != 200:
                    raise RuntimeError(f"bot state HTTP {status}")
                source = json.loads(body)
                return self._json(200, self.bot_context.project(source))
            except Exception as exc:  # noqa: BLE001
                self.context.log(
                    "command-center: contexto Bot fallo "
                    f"({type(exc).__name__})"
                )
                return self._json(
                    502,
                    error_document(
                        "bot-context.unavailable",
                        "No fue posible leer el estado del Bot.",
                        502,
                        retryable=True,
                    ),
                )
        if subpath == "media-artwork":
            provider = query.get("provider", "apple-music")
            if provider in {"qobuz", "tidal"}:
                resolver = getattr(self, "_external_artwork", None)
                artwork = (
                    resolver.artwork(provider, query.get("v", ""))
                    if resolver is not None
                    else None
                )
                if artwork is not None:
                    data, content_type = artwork
                    return 200, content_type, data
                return self._json(
                    404,
                    error_document(
                        "media-artwork.unavailable",
                        "No existe una caratula externa validada.",
                        404,
                    ),
                )
            if provider != "apple-music" or self._apple_music is None:
                return self._json(
                    404,
                    error_document(
                        "media-artwork.unavailable",
                        "No existe una caratula local disponible.",
                        404,
                    ),
                )
            try:
                version = query.get("v", "")
                item_ref = self._apple_music.current_item_ref
                expected_version = (
                    hashlib.sha256(item_ref.encode("utf-8")).hexdigest()[:16]
                    if isinstance(item_ref, str)
                    else ""
                )
                if version != expected_version:
                    raise LookupError("artwork version mismatch")
                artwork = asyncio.run(
                    self._apple_music.artwork(
                        OperationContext.with_timeout(1.5),
                        expected_item_ref=item_ref,
                    )
                )
                if artwork is None:
                    raise LookupError("artwork unavailable")
                data, content_type = artwork
                return 200, content_type, data
            except Exception as exc:  # noqa: BLE001
                self.context.log(
                    "command-center: caratula multimedia no disponible "
                    f"({type(exc).__name__})"
                )
                return self._json(
                    404,
                    error_document(
                        "media-artwork.unavailable",
                        "No existe una caratula local disponible.",
                        404,
                    ),
                )
        if subpath == "media-context":
            provider = query.get("provider", "apple-music")
            if provider == "auto":
                preferred = query.get("preferred", "apple-music")
                if preferred not in _MEDIA_PROVIDERS:
                    preferred = "apple-music"
                try:
                    return self._json(
                        200,
                        asyncio.run(
                            self._automatic_media_snapshot(preferred)
                        ),
                    )
                except Exception as exc:  # noqa: BLE001
                    self.context.log(
                        "command-center: seleccion multimedia fallo "
                        f"({type(exc).__name__})"
                    )
                    return self._json(
                        502,
                        error_document(
                            "media-context.unavailable",
                            "No fue posible detectar el reproductor activo.",
                            502,
                            retryable=True,
                        ),
                    )
            surface = self._media_surface_for(provider)
            if surface is None:
                return self._json(
                    400,
                    error_document(
                        "media-context.provider-invalid",
                        "El proveedor multimedia no es valido.",
                        400,
                    ),
                )
            try:
                snapshot = self._cached_media_snapshot_sync(provider)
                snapshot["selected_provider"] = provider
                snapshot["available_providers"] = list(_MEDIA_PROVIDERS)
                return self._json(200, snapshot)
            except Exception as exc:  # noqa: BLE001
                self.context.log(
                    "command-center: contexto multimedia fallo "
                    f"({type(exc).__name__})"
                )
                return self._json(
                    502,
                    error_document(
                        "media-context.unavailable",
                        "No fue posible leer el reproductor local.",
                        502,
                        retryable=True,
                    ),
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

    async def api_post(self, subpath, body, headers, user=None):
        if subpath != "media-command":
            return None
        if not user:
            return self._json(
                401,
                error_document(
                    "auth.required",
                    "Se requiere una sesion autenticada.",
                    401,
                ),
            )
        if not isinstance(body, dict):
            return self._json(
                400,
                error_document(
                    "media-command.invalid",
                    "El comando multimedia no es valido.",
                    400,
                ),
            )
        allowed = {
            "play": MediaAction.PLAY,
            "pause": MediaAction.PAUSE,
            "next": MediaAction.NEXT,
            "previous": MediaAction.PREVIOUS,
            "open_app": MediaAction.OPEN_APP,
        }
        action = allowed.get(body.get("action"))
        command_id = body.get("command_id")
        provider = body.get("provider", "apple-music")
        surface = self._media_surface_for(provider)
        if (
            action is None
            or not isinstance(command_id, str)
            or surface is None
        ):
            return self._json(
                400,
                error_document(
                    "media-command.invalid",
                    "Accion o command_id invalido.",
                    400,
                ),
            )
        try:
            result = await surface.execute(
                command_id=command_id,
                action=action,
            )
            self._invalidate_media_snapshot(provider)
            return self._json(200, result)
        except MediaCommandsDisabled:
            return self._json(
                409,
                error_document(
                    "media-command.disabled",
                    "El controlador multimedia local no esta habilitado.",
                    409,
                ),
            )
        except ValueError:
            return self._json(
                400,
                error_document(
                    "media-command.invalid",
                    "El comando multimedia no cumple el contrato.",
                    400,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            self.context.log(
                "command-center: comando multimedia fallo "
                f"({type(exc).__name__})"
            )
            return self._json(
                502,
                error_document(
                    "media-command.unavailable",
                    "No fue posible confirmar el comando multimedia.",
                    502,
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
            "module_registry": self.module_registry.stats(),
            "market_ribbon": self.market_ribbon.stats(),
            "interfaces": {
                "chart_provider": {
                    "version": CHART_PROVIDER_INTERFACE_VERSION,
                    "status": "contract-only",
                },
                "media_controller": {
                    "version": MEDIA_CONTROLLER_INTERFACE_VERSION,
                    "status": (
                        "local-opt-in"
                        if self._local_media_enabled
                        else "contract-only"
                    ),
                },
            },
            "surface": "visual-experimental",
        }

    @staticmethod
    def _module_json_payload(response, *, allow_forbidden: bool = False):
        if response is None:
            raise RuntimeError("module response unavailable")
        status, _content_type, body = response
        if allow_forbidden and status in {401, 403}:
            return None
        if status != 200:
            raise RuntimeError(f"module response HTTP {status}")
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise RuntimeError("module payload invalid")
        return payload

    async def websocket(self, peer, user_loader) -> None:
        await self.gateway.handle(peer, user_loader)


def get_module(context):
    return CommandCenterModule(context)
