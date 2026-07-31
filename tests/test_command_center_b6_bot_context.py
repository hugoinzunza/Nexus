import json
import subprocess
from pathlib import Path

from modules.command_center.bot_context import BotContextService
from modules.command_center.contracts import CONTRACT_V1_FINGERPRINT
from modules.command_center.module import CommandCenterModule
from modules.command_center.module_registry import command_center_module_registry


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "modules" / "command_center" / "public"
NOW = 1_800_000_000_000


def _source(**overrides):
    source = {
        "source": "vps",
        "age_seconds": 8,
        "live": False,
        "active": False,
        "kill": False,
        "account": {"balance": 1000, "api_key": "secret"},
        "positions": [{"symbol": "BTCUSDT", "qty": 1}],
        "open_orders": [{"order_id": 99}],
        "summary": {"pnl_usd": -100},
        "trades": [
            {
                "pair": "BTC_USDT",
                "dir": "short",
                "mode": "dry",
                "status": "abierta",
                "opened_at": NOW // 1000 - 300,
                "entry_price": 64_000,
                "sl": 65_000,
                "tp": 60_000,
                "pnl_usd": 25,
            }
        ],
    }
    source.update(overrides)
    return source


def test_proyeccion_b6_descarta_cuenta_ordenes_precios_y_pnl() -> None:
    result = BotContextService(clock_ms=lambda: NOW).project(_source())
    encoded = json.dumps(result)

    assert result["state"] == "ready"
    assert result["mode"] == "dry-run"
    assert result["severity"] == "info"
    assert result["read_only"] is True
    assert result["latest_signal"] == {
        "pair": "BTC",
        "direction": "short",
        "status": "abierta",
        "mode": "dry",
        "occurred_at_ms": NOW - 300_000,
        "age_seconds": 300.0,
    }
    for forbidden in (
        "account",
        "positions",
        "orders",
        "balance",
        "entry",
        "sl",
        "tp",
        "pnl",
        "secret",
    ):
        assert forbidden not in encoded.lower()


def test_estado_operacional_distingue_live_pausa_y_stale() -> None:
    service = BotContextService(clock_ms=lambda: NOW)

    live = service.project(_source(live=True, active=True))
    paused = service.project(_source(live=True, active=True, kill=True))
    stale = service.project(_source(age_seconds=121))

    assert (live["state"], live["mode"], live["severity"]) == (
        "ready",
        "live",
        "normal",
    )
    assert (paused["state"], paused["severity"]) == ("paused", "warning")
    assert (stale["state"], stale["severity"]) == ("degraded", "warning")


def test_endpoint_respeta_autorizacion_del_modulo_bot(monkeypatch) -> None:
    from core.app import hub

    class Bot:
        def __init__(self):
            self.user = None

        def api(self, subpath, query, user=None):
            self.user = user
            return (
                200,
                "application/json",
                json.dumps(_source()).encode(),
            )

    bot = Bot()
    monkeypatch.setitem(hub.modules_by_slug, "bot", bot)
    module = object.__new__(CommandCenterModule)
    module.bot_context = BotContextService(clock_ms=lambda: NOW)
    module.context = type("Context", (), {"log": lambda *_args: None})()

    response = module.api("bot-context", {}, user={"id": 7, "role": "admin"})

    assert response[0] == 200
    assert bot.user["id"] == 7
    assert json.loads(response[2])["read_only"] is True
    assert command_center_module_registry().stats()["attached_factories"] == 0
    assert CONTRACT_V1_FINGERPRINT == (
        "b0a8a7efa623a1aae4b681c3cfc42790d36a6a14fbc689688026c523f2e49b46"
    )


def test_endpoint_falla_cerrado_si_bot_rechaza_usuario(monkeypatch) -> None:
    from core.app import hub

    class Bot:
        @staticmethod
        def api(subpath, query, user=None):
            return 401, "application/json", b'{"error":"no autorizado"}'

    monkeypatch.setitem(hub.modules_by_slug, "bot", Bot())
    module = object.__new__(CommandCenterModule)
    module.bot_context = BotContextService(clock_ms=lambda: NOW)
    module.context = type("Context", (), {"log": lambda *_args: None})()

    response = module.api("bot-context", {}, user={"id": 8})

    assert response[0] == 403
    assert json.loads(response[2])["code"] == "bot-context.forbidden"


def test_frontend_normaliza_y_no_inventa_una_senal() -> None:
    script_uri = (PUBLIC / "command-center.js").resolve().as_uri()
    node = f"""
      import({json.dumps(script_uri)}).then((module) => {{
        process.stdout.write(JSON.stringify({{
          empty: module.normalizeBotContext(null),
          valid: module.normalizeBotContext({{
            state: "paused", mode: "live", severity: "warning",
            source_age_seconds: 4, read_only: true,
            latest_signal: {{
              pair: "ETH", direction: "long", status: "abierta",
              mode: "live", occurred_at_ms: {NOW}
            }}
          }})
        }}));
      }});
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", node],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["empty"]["state"] == "unknown"
    assert payload["empty"]["latestSignal"] is None
    assert payload["valid"]["mode"] == "live"
    assert payload["valid"]["latestSignal"]["pair"] == "ETH"


def test_b6_agrega_un_panel_read_only_sin_controles() -> None:
    page = (PUBLIC / "index.html").read_text(encoding="utf-8")
    script = (PUBLIC / "command-center.js").read_text(encoding="utf-8")

    assert page.count('class="bot-context-panel"') == 1
    panel = page.split('class="bot-context-panel"', 1)[1].split(
        "</section>", 1
    )[0]
    assert "solo lectura" in panel
    assert "<button" not in panel
    assert "<a " not in panel
    assert "/m/command-center/api/bot-context" in script
    assert "method: \"POST\"" not in script
