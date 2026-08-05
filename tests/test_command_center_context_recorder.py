import json
import os
import threading
import time
from pathlib import Path

import pytest

from core.module_base import ModuleContext
from core.vault import generate_keypair
from modules.command_center.context_recorder import (
    ContextRecorderIntegrityError,
    MarketContextRecorder,
    SCHEMA,
)
from modules.command_center.market_ribbon import MarketRibbonService
from modules.command_center.module import CommandCenterModule
from modules.command_center.context_storage import ContextStorageManager


NOW = 1_800_000_000_000


def _snapshot(*, generated_at_ms=NOW, price=70_000.0, observed_at_ms=NOW):
    return {
        "generated_at_ms": generated_at_ms,
        "assets": [
            {
                "id": "btcusdt",
                "price": price,
                "change_pct": 1.2,
                "observed_at_ms": observed_at_ms,
                "freshness": "live",
                "source": "Binance Futures",
                "kind": "futures",
            }
        ],
        "provider_errors": [],
    }


def _events(path: Path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_recorder_encadena_observaciones_forward_y_reanuda_tras_reinicio(tmp_path):
    path = tmp_path / "context.jsonl"
    now = [NOW]
    recorder = MarketContextRecorder(path, clock_ms=lambda: now[0])

    assert recorder.record(_snapshot()) is True
    now[0] += 30_000
    assert recorder.record(
        _snapshot(generated_at_ms=now[0], observed_at_ms=now[0], price=70_100)
    ) is True

    rows = _events(path)
    assert [row["sequence"] for row in rows] == [1, 2]
    assert rows[0]["schema"] == SCHEMA
    assert rows[1]["previous_hash"] == rows[0]["event_hash"]
    assert rows[1]["snapshot"]["provenance"].endswith(".forward")

    restarted = MarketContextRecorder(path, clock_ms=lambda: now[0] + 30_000)
    assert restarted.stats()["sequence"] == 2
    assert restarted.record(
        _snapshot(
            generated_at_ms=now[0] + 30_000,
            observed_at_ms=now[0] + 30_000,
            price=70_200,
        )
    ) is True
    assert _events(path)[-1]["sequence"] == 3


def test_recorder_no_duplica_el_mismo_snapshot(tmp_path):
    path = tmp_path / "context.jsonl"
    recorder = MarketContextRecorder(path, clock_ms=lambda: NOW)

    assert recorder.record(_snapshot()) is True
    assert recorder.record(_snapshot()) is False
    assert len(_events(path)) == 1
    assert recorder.stats()["duplicates"] == 1


def test_recorder_serializa_escritores_concurrentes_y_restringe_permisos(tmp_path):
    path = tmp_path / "context.jsonl"
    start = threading.Barrier(3)
    failures = []

    def write(price):
        recorder = MarketContextRecorder(path, clock_ms=lambda: NOW)
        start.wait()
        try:
            recorder.record(_snapshot(price=price))
        except Exception as exc:  # pragma: no cover - se reporta abajo
            failures.append(exc)

    threads = [
        threading.Thread(target=write, args=(70_001.0,)),
        threading.Thread(target=write, args=(70_002.0,)),
    ]
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join()

    assert failures == []
    rows = _events(path)
    assert [row["sequence"] for row in rows] == [1, 2]
    assert rows[1]["previous_hash"] == rows[0]["event_hash"]
    assert os.stat(path).st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "snapshot",
    [
        _snapshot(generated_at_ms=NOW - 120_001),
        _snapshot(generated_at_ms=NOW + 30_001),
        _snapshot(observed_at_ms=NOW + 30_001),
    ],
)
def test_recorder_rechaza_backfill_y_timestamps_futuros(tmp_path, snapshot):
    recorder = MarketContextRecorder(tmp_path / "context.jsonl", clock_ms=lambda: NOW)

    with pytest.raises(ValueError):
        recorder.record(snapshot)

    assert recorder.stats()["sequence"] == 0
    assert recorder.stats()["rejected"] == 1


def test_recorder_detecta_manipulacion_al_reiniciar(tmp_path):
    path = tmp_path / "context.jsonl"
    recorder = MarketContextRecorder(path, clock_ms=lambda: NOW)
    recorder.record(_snapshot())
    event = _events(path)[0]
    event["snapshot"]["assets"][0]["price"] = 1
    path.write_text(json.dumps(event) + "\n")

    with pytest.raises(ContextRecorderIntegrityError):
        MarketContextRecorder(path, clock_ms=lambda: NOW)


def test_recorder_rechaza_regresion_del_reloj_de_captura(tmp_path):
    path = tmp_path / "context.jsonl"
    now = [NOW]
    recorder = MarketContextRecorder(path, clock_ms=lambda: now[0])
    recorder.record(_snapshot())
    now[0] -= 1

    with pytest.raises(ValueError):
        recorder.record(
            _snapshot(
                generated_at_ms=now[0],
                observed_at_ms=now[0],
                price=70_001,
            )
        )

    assert len(_events(path)) == 1
    assert recorder.stats()["rejected"] == 1


def test_market_ribbon_observa_solo_refresh_y_aisla_fallo_del_recorder():
    calls = []
    clock = [NOW]

    def observer(snapshot):
        calls.append(snapshot["generated_at_ms"])
        if len(calls) == 2:
            raise OSError("disk unavailable")

    class MinimalRibbon(MarketRibbonService):
        def _load_yahoo(self):
            return []

        def _load_total(self):
            return []

        def _load_futures(self):
            return [_snapshot()["assets"][0]]

    service = MinimalRibbon(
        clock_ms=lambda: clock[0],
        ttl_ms=15_000,
        snapshot_observer=observer,
    )

    first = service.snapshot()
    cached = service.snapshot()
    clock[0] += 15_001
    second = service.snapshot()

    assert first["generated_at_ms"] == cached["generated_at_ms"]
    assert second["generated_at_ms"] == clock[0]
    assert calls == [NOW, clock[0]]
    assert service.stats()["observer_failures"] == 1


def test_recorder_no_contiene_comparacion_ni_lenguaje_temporal():
    source = (
        Path(__file__).parents[1]
        / "modules"
        / "command_center"
        / "context_recorder.py"
    ).read_text()

    for phrase in (
        "hace una hora",
        '"continua"',
        '"mantiene"',
        "cambio de regimen",
    ):
        assert phrase not in source.lower()


def test_modulo_puede_reportar_log_corrupto_sin_caerse(tmp_path):
    path = tmp_path / "context.jsonl"
    path.write_text('{"schema":"roto"}\n')

    recorder = MarketContextRecorder(
        path,
        clock_ms=lambda: NOW,
        strict_existing=False,
    )

    assert recorder.stats()["status"] == "failed"
    with pytest.raises(ContextRecorderIntegrityError):
        recorder.record(_snapshot())


def test_recorder_reporta_fallo_de_escritura_sin_crear_historia(tmp_path):
    parent_as_file = tmp_path / "not-a-directory"
    parent_as_file.write_text("occupied")
    recorder = MarketContextRecorder(
        parent_as_file / "context.jsonl",
        clock_ms=lambda: NOW,
    )

    with pytest.raises(OSError):
        recorder.record(_snapshot())

    assert recorder.stats()["status"] == "failed"
    assert recorder.stats()["sequence"] == 0


def test_colector_headless_no_depende_de_que_la_pagina_este_abierta():
    calls = []

    class Ribbon:
        def snapshot(self):
            calls.append(time.monotonic())
            return {}

    module = object.__new__(CommandCenterModule)
    module.market_ribbon = Ribbon()
    module.context = type("Context", (), {"log": lambda *_args: None})()
    module._context_recorder_stop = __import__("threading").Event()
    module._context_recorder_thread = None
    module._context_recorder_poll_seconds = 0.01
    module._context_recorder_enabled = True

    module.start()
    deadline = time.monotonic() + 0.3
    while len(calls) < 2 and time.monotonic() < deadline:
        time.sleep(0.005)
    module.stop()

    assert len(calls) >= 2
    assert module._context_recorder_thread is None


def test_colector_no_arranca_sin_persistencia_y_respaldo_confirmados():
    module = object.__new__(CommandCenterModule)
    module._context_recorder_enabled = False
    module._context_recorder_thread = None

    module.start()

    assert module._context_recorder_thread is None


def test_activacion_exige_solicitud_persistencia_y_respaldo(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "NEXUX_CONTEXT_STORAGE_ROOT",
        str(tmp_path / "storage"),
    )
    monkeypatch.setenv("NEXUX_CONTEXT_RECORDER_ENABLED", "1")
    context = ModuleContext(
        "command_center",
        str(Path(__file__).parents[1] / "modules" / "command_center"),
        {},
        lambda _message: None,
    )

    blocked = CommandCenterModule(context)
    assert blocked._context_recorder_enabled is False
    assert blocked.market_ribbon._snapshot_observer is None

    storage = ContextStorageManager(tmp_path / "storage")
    storage.initialize()
    drill_source = ContextStorageManager(tmp_path / "drill-source")
    drill_source.initialize()
    clock = [NOW]
    recorder = MarketContextRecorder(
        drill_source.active_path,
        clock_ms=lambda: clock[0],
        coordination_lock_path=drill_source.coordination_lock_path,
    )
    recorder.record(_snapshot())
    drill_source.rotate_if_needed(force=True)
    private_pem, public_pem = generate_keypair()
    backup_root = tmp_path / "backup"
    public_key_file = tmp_path / "context-vault-public.pem"
    public_key_file.write_text(public_pem)
    drill_source.backup_closed_segments(backup_root, public_pem)
    restored = ContextStorageManager.restore_vaults(
        backup_root.glob("segment-*.vault.json"),
        tmp_path / "restored",
        private_pem,
    )
    storage.record_isolated_restore_drill(drill_source.root, restored.root)

    assert storage.audit()["segment_count"] == 0
    assert storage.health()["restore_drill_verified"] is True

    monkeypatch.setenv("NEXUX_CONTEXT_RECORDER_PERSISTENCE_CONFIRMED", "1")
    monkeypatch.setenv("NEXUX_CONTEXT_RECORDER_BACKUP_CONFIRMED", "1")
    monkeypatch.setenv("NEXUX_CONTEXT_BACKUP_ROOT", str(backup_root))
    monkeypatch.setenv(
        "NEXUX_CONTEXT_VAULT_PUBLIC_FILE",
        str(public_key_file),
    )
    authorized = CommandCenterModule(context)
    assert authorized._context_recorder_enabled is False
    assert authorized._context_recorder_blockers == ["release_not_authorized"]
    assert authorized.market_ribbon._snapshot_observer is None


def test_cierre_de_segmento_dispara_vault_y_falla_cerrado(tmp_path):
    calls = []

    class Storage:
        def ensure_capacity(self):
            calls.append("capacity")

        def rotate_if_needed(self):
            calls.append("rotate")
            return {"segment_id": "segment-000001"}

        def backup_closed_segments(self, destination, public_pem):
            calls.append(("backup", destination, public_pem))

    class Recorder:
        def record(self, snapshot):
            calls.append(("record", snapshot))
            return True

    public_key = tmp_path / "public.pem"
    public_key.write_text("public material")
    module = object.__new__(CommandCenterModule)
    module.context_storage = Storage()
    module.context_recorder = Recorder()
    module._context_storage_failed = False
    module._context_backup_root = str(tmp_path / "external")
    module._context_vault_public_file = str(public_key)

    assert module._record_context_snapshot({"snapshot": 1}) is True
    assert calls[-1] == (
        "backup",
        str(tmp_path / "external"),
        "public material",
    )

    module.context_storage.ensure_capacity = lambda: (_ for _ in ()).throw(
        OSError("disk unavailable")
    )
    with pytest.raises(OSError):
        module._record_context_snapshot({"snapshot": 2})
    assert module._context_storage_failed is True
    with pytest.raises(RuntimeError, match="blocked"):
        module._record_context_snapshot({"snapshot": 3})
