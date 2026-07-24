#!/usr/bin/env python3
"""Read Telegram + public BTC candles and publish the CoinSignals shadow snapshot."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from telethon import TelegramClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.coinsignals_backtest import KlineCache
from modules.coinsignals.coinglass import update_market_context
from modules.coinsignals.module import STATE_PATH
from modules.coinsignals.shadow import HISTORY_PATH, build_snapshot

DEFAULT_CONFIG = Path.home() / ".config/nexux/telegram.env"
DEFAULT_SESSION = Path.home() / ".config/nexux/coinsignals"
COINGLASS_PATH = ROOT / "data/coinsignals_coinglass.json"


def load_env(path: Path) -> dict[str, str]:
    values = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def serialize(message: Any) -> dict[str, Any]:
    reply = getattr(message, "reply_to", None)
    media = getattr(message, "media", None)
    return {
        "id": message.id,
        "date": message.date.isoformat(),
        "edit_date": message.edit_date.isoformat() if message.edit_date else None,
        "text": message.message or "",
        "reply_to_msg_id": getattr(reply, "reply_to_msg_id", None),
        "grouped_id": getattr(message, "grouped_id", None),
        "post_author": getattr(message, "post_author", None),
        "views": getattr(message, "views", None),
        "forwards": getattr(message, "forwards", None),
        "media_type": type(media).__name__ if media is not None else None,
    }


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(path)


async def refresh_telegram(config: Path, session: Path, channel_title: str) -> int:
    env = load_env(config)
    client = TelegramClient(str(session), int(env["TELEGRAM_API_ID"]), env["TELEGRAM_API_HASH"])
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram session is not authorized; run the export login first")
        entity = None
        async for dialog in client.iter_dialogs():
            if dialog.name.strip().casefold() == channel_title.strip().casefold():
                entity = dialog.entity
                break
        if entity is None:
            raise RuntimeError(f"Telegram channel not found: {channel_title}")
        payload = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        by_id = {int(message["id"]): message for message in payload.get("messages", [])}
        async for message in client.iter_messages(entity, limit=500):
            by_id[message.id] = serialize(message)
        messages = [by_id[key] for key in sorted(by_id)]
        payload.update(
            {
                "research_only": True,
                "source": "telegram_mtproto_user_api",
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "channel": {"title": channel_title, "id": entity.id},
                "message_count": len(messages),
                "messages": messages,
            }
        )
        atomic_json(HISTORY_PATH, payload)
        return len(messages)
    finally:
        await client.disconnect()


def publish_remote(snapshot: dict[str, Any], remote_url: str, token: str) -> None:
    if not remote_url:
        return
    request = urllib.request.Request(
        remote_url.rstrip("/") + "/m/coinsignals/api/ingest",
        data=json.dumps(snapshot, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Nexus-Token": token},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError(f"remote ingest returned HTTP {response.status}")


async def refresh(args: argparse.Namespace) -> dict[str, Any]:
    message_count = await refresh_telegram(args.config, args.session, args.channel)
    cache = KlineCache()
    cached = cache.load("BTCUSDT")
    start_ms = int(cached[0]["t"]) if cached else int((time.time() - 6 * 365 * 86400) * 1000)
    cache.fetch("BTCUSDT", start_ms, int(time.time() * 1000))
    market_context = None
    if args.coinglass_api_key:
        market_context, _history = update_market_context(
            args.coinglass_api_key,
            COINGLASS_PATH,
            max_age_seconds=args.coinglass_interval,
        )
    snapshot = build_snapshot(
        forward_start=args.forward_start,
        market_context=market_context,
    )
    atomic_json(Path(STATE_PATH), snapshot)
    remote_status = "local-only"
    if args.remote_url:
        try:
            publish_remote(snapshot, args.remote_url, args.token)
            remote_status = "remote-ok"
        except Exception as exc:  # noqa: BLE001
            # La captura local es la fuente de verdad. Una caída de Railway no debe
            # perder mensajes ni convertir el timer en fallido; el próximo ciclo
            # vuelve a intentar publicar el snapshot completo.
            remote_status = f"remote-pending ({exc})"
    print(
        f"coinsignals shadow: {message_count} mensajes, "
        f"{sum(book['metrics']['signals'] for book in snapshot['books'])} registros en libros, "
        f"{remote_status}"
    )
    return snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--session", type=Path, default=DEFAULT_SESSION)
    parser.add_argument("--channel", default="Vip CoinSignals")
    parser.add_argument("--forward-start", default="2026-07-22T00:00:00+00:00")
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--remote-url", default=os.environ.get("NEXUS_REMOTE_URL", ""))
    parser.add_argument("--token", default=os.environ.get("NEXUS_INGEST_TOKEN", ""))
    parser.add_argument("--coinglass-api-key", default=os.environ.get("COINGLASS_API_KEY", ""))
    parser.add_argument("--coinglass-interval", type=int, default=300)
    return parser.parse_args()


if __name__ == "__main__":
    options = parse_args()
    while True:
        asyncio.run(refresh(options))
        if options.once:
            break
        time.sleep(max(30, options.interval))
