import json
import subprocess
from pathlib import Path

from modules.command_center.module import CommandCenterModule
from modules.command_center.positions_context import PositionsContextService


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "modules" / "command_center" / "public"
NOW = 1_800_000_000_000


def _journal(*, age=8):
    return {
        "has_data": True,
        "age_seconds": age,
        "futures": {
            "ok": True,
            "balance": {
                "wallet": 12_500,
                "available": 10_000,
                "unrealized": 42.5,
            },
            "open_positions": [
                {
                    "symbol": "BTCUSDT",
                    "side": "LONG",
                    "size": 0.1,
                    "entry": 60_000,
                    "mark": 61_000,
                    "unrealized": 100,
                    "leverage": 5,
                }
            ],
        },
    }


def _bot():
    return {
        "source": "vps",
        "age_seconds": 4,
        "live": False,
        "positions": [],
        "account": {},
        "testnet": {
            "active": True,
            "live_virtual": True,
            "account": {
                "balance": 5_000,
                "available": 4_500,
                "unrealized_pnl": -5,
            },
            "positions": [
                {
                    "symbol": "SOLUSDT",
                    "side": "SHORT",
                    "qty": 20,
                    "entry": 80,
                    "mark": 80.5,
                    "margin": 322,
                    "unrealized_pnl": -10,
                    "leverage": 5,
                }
            ],
        },
    }


def test_proyecta_cuentas_separadas_pnl_roe_y_origen() -> None:
    result = PositionsContextService(clock_ms=lambda: NOW).project(
        _journal(),
        _bot(),
    )

    principal, bot = result["accounts"]
    assert result["state"] == "ready"
    assert result["total_positions"] == 2
    assert result["read_only"] is True
    assert principal["environment"] == "live"
    assert principal["positions"][0]["pnl"] == 100
    assert round(principal["positions"][0]["roe"], 2) == 8.2
    assert bot["environment"] == "testnet"
    assert bot["positions"][0]["side"] == "SHORT"
    assert round(bot["positions"][0]["roe"], 2) == -3.11


def test_datos_antiguos_no_se_presentan_como_live() -> None:
    result = PositionsContextService(clock_ms=lambda: NOW).project(
        _journal(age=3600),
        None,
    )

    assert result["state"] == "degraded"
    assert result["accounts"][0]["state"] == "stale"
    assert result["accounts"][0]["detail"] == "Datos antiguos"
    assert result["accounts"][1]["state"] == "unavailable"

    local = PositionsContextService(clock_ms=lambda: NOW).project(
        _journal(),
        {"source": "local", "positions": [], "account": {}},
    )
    assert local["accounts"][1]["detail"] == "Sin snapshot del VPS"


def test_endpoint_usa_diario_por_usuario_y_bot_solo_si_autorizado(monkeypatch) -> None:
    class Source:
        def __init__(self, response):
            self.response = response
            self.users = []

        def api(self, _subpath, _query, user=None):
            self.users.append(user)
            return self.response

    journal = Source((200, "application/json", json.dumps(_journal()).encode()))
    bot = Source((401, "application/json", b'{"error":"no autorizado"}'))
    from core.app import hub

    monkeypatch.setitem(hub.modules_by_slug, "journal", journal)
    monkeypatch.setitem(hub.modules_by_slug, "bot", bot)
    module = object.__new__(CommandCenterModule)
    module.positions_context = PositionsContextService(clock_ms=lambda: NOW)
    module.context = type("Context", (), {"log": lambda *_args: None})()
    user = {"uid": 7, "role": "user"}

    assert module.api("positions-context", {}, user=None)[0] == 401
    response = module.api("positions-context", {}, user=user)
    payload = json.loads(response[2])

    assert response[0] == 200
    assert journal.users == [user]
    assert bot.users == [user]
    assert payload["accounts"][0]["state"] == "ready"
    assert payload["accounts"][1]["state"] == "unavailable"


def test_frontend_normaliza_sin_inventar_numeros_o_cuentas() -> None:
    script_uri = (PUBLIC / "command-center.js").resolve().as_uri()
    node = f"""
      import({json.dumps(script_uri)}).then((module) => {{
        process.stdout.write(JSON.stringify({{
          empty: module.normalizePositionsContext(null),
          valid: module.normalizePositionsContext({{
            state: "ready", total_positions: 1, read_only: true,
            generated_at_ms: {NOW}, accounts: [{{
              id: "principal", label: "Principal", state: "ready",
              environment: "live", total_pnl: "12.5",
              positions: [{{symbol: "BTCUSDT", side: "SHORT", pnl: "12.5",
                roe: "4.2", entry: "60000", mark: "59000", leverage: "5"}}]
            }}]
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

    assert [a["id"] for a in payload["empty"]["accounts"]] == ["principal", "bot"]
    assert payload["empty"]["totalPositions"] == 0
    assert payload["valid"]["accounts"][0]["positions"][0]["side"] == "SHORT"
    assert payload["valid"]["accounts"][0]["totalPnl"] == 12.5


def test_panel_no_contiene_controles_de_ordenes_ni_credenciales() -> None:
    page = (PUBLIC / "index.html").read_text(encoding="utf-8")
    source = (
        ROOT / "modules" / "command_center" / "positions_context.py"
    ).read_text(encoding="utf-8")
    panel = page.split('class="positions-panel"', 1)[1].split(
        '<section class="bot-context-panel"', 1
    )[0]

    assert "<button" not in panel
    assert "<input" not in panel
    assert "market_order" not in source
    assert "api_secret" not in source
    assert "BINANCE_" not in source
