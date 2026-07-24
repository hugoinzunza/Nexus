import json
from pathlib import Path

from core.module_base import ModuleContext
from modules.coinsignals.shadow import BOOKS, build_snapshot


ROOT = Path(__file__).resolve().parents[1]


def test_shadow_snapshot_has_three_books_and_no_execution(tmp_path):
    history_path = tmp_path / "coinsignals-history.json"
    history_path.write_text(
        json.dumps({"exported_at": None, "messages": []}),
        encoding="utf-8",
    )
    snapshot = build_snapshot(
        history_path,
        forward_start="2026-07-22T00:00:00+00:00",
        candles=[],
    )
    assert snapshot["research_only"] is True
    assert snapshot["execution_enabled"] is False
    assert snapshot["mode"] == "shadow"
    assert [book["id"] for book in snapshot["books"]] == [row[0] for row in BOOKS]
    assert snapshot["entry_policy"]["planned"] == "equal USDT per entry; harmonic average"


def test_web_module_has_no_trading_executor_dependency():
    source = (ROOT / "modules/coinsignals/module.py").read_text(encoding="utf-8")
    shadow = (ROOT / "modules/coinsignals/shadow.py").read_text(encoding="utf-8")
    combined = source + shadow
    assert "modules.bot" not in combined
    assert "BotExecutor" not in combined
    assert "place_order" not in combined
    assert "api_secret" not in combined


def test_ingest_rejects_any_execution_enabled_snapshot(monkeypatch, tmp_path):
    import modules.coinsignals.module as module

    monkeypatch.setattr(module, "STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("NEXUS_INGEST_TOKEN", "secret")
    context = ModuleContext("coinsignals", str(tmp_path), {}, lambda _message: None)
    instance = module.CoinSignalsModule(context)
    status, _, raw = instance.api_post(
        "ingest",
        {"research_only": True, "execution_enabled": True, "mode": "shadow"},
        {"x-nexus-token": "secret"},
    )
    assert status == 400
    assert "solo se aceptan" in json.loads(raw)["error"]


def test_panel_names_planned_and_confirmed_entry_separately():
    html = (ROOT / "modules/coinsignals/public/index.html").read_text(encoding="utf-8")
    script = (ROOT / "modules/coinsignals/public/app.js").read_text(encoding="utf-8")
    assert "Entrada plan" in html
    assert "Promedio confirmado" in html
    assert "SHADOW ONLY" in html
    assert "COINGLASS · RESEARCH ONLY" in html
    assert "Cambio OI ${intervals.open_interest" in script
