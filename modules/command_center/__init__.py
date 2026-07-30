"""Infraestructura headless del NEXUX Command Center."""

from .chart_provider import ChartProvider, ChartProviderRouter
from .conformance import HeadlessIntegrationHarness
from .fake_adapters import FakeChartProvider, FakeMediaController
from .media_controller import MediaController, MediaControllerRouter
from .module_registry import StaticModuleRegistry

__all__ = (
    "ChartProvider",
    "ChartProviderRouter",
    "FakeChartProvider",
    "FakeMediaController",
    "HeadlessIntegrationHarness",
    "MediaController",
    "MediaControllerRouter",
    "StaticModuleRegistry",
)
