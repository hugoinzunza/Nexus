#!/usr/bin/env python3
"""Exporta eventos estructurados de HechosEsencialesChile con Telethon.

No se une al grupo: exige que la sesión indicada ya sea miembro. Solo persiste
campos del bot; descarta conversación humana y no descarga documentos.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys
from datetime import datetime, timezone

from telethon import TelegramClient

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.paths import persist_dir  # noqa: E402
from modules.acciones_chile.telegram_events import parse_event  # noqa: E402


def load_env(path: pathlib.Path) -> dict[str, str]:
    values = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def atomic_json(path: pathlib.Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(path)


async def refresh(args) -> dict:
    env = load_env(args.config)
    client = TelegramClient(str(args.session), int(env["TELEGRAM_API_ID"]), env["TELEGRAM_API_HASH"])
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError("la sesión Telegram indicada no está autorizada")
        entity = None
        async for dialog in client.iter_dialogs():
            if (dialog.name or "").strip().casefold() == args.channel.casefold():
                entity = dialog.entity
                break
        if entity is None:
            raise RuntimeError("la sesión no pertenece a HechosEsencialesChile")
        events = []
        async for message in client.iter_messages(entity, limit=args.limit):
            event = parse_event(message.id, message.date.isoformat(), message.message or "")
            if event:
                events.append(event)
        events.sort(key=lambda event: event["available_at"], reverse=True)
        payload = {
            "schema_version": "acciones-chile-telegram-events-0.1.0",
            "source": "telegram:hechosesencialeschile",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "personal_use_only": True,
            "documents_downloaded": False,
            "event_count": len(events),
            "events": events,
        }
        atomic_json(args.output, payload)
        return payload
    finally:
        await client.disconnect()


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=pathlib.Path,
                        default=pathlib.Path.home() / ".config/nexux/telegram.env")
    parser.add_argument("--session", type=pathlib.Path, required=True,
                        help="sesión Telethon ya autorizada y miembro del grupo")
    parser.add_argument("--channel", default="HechosEsencialesChile")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--output", type=pathlib.Path,
                        default=pathlib.Path(persist_dir(str(ROOT))) / "acciones_chile_telegram_events.json")
    return parser.parse_args()


if __name__ == "__main__":
    result = asyncio.run(refresh(parse_args()))
    print(json.dumps({"ok": True, "events": result["event_count"]}, ensure_ascii=False))
