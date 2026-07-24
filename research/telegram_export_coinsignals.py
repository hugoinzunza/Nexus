#!/usr/bin/env python3
"""Export one Telegram channel to JSON for offline research."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import qrcode
from telethon import TelegramClient, errors


DEFAULT_CONFIG = Path.home() / ".config" / "nexux" / "telegram.env"
DEFAULT_SESSION = Path.home() / ".config" / "nexux" / "coinsignals"
DEFAULT_OUTPUT = Path("data/telegram/coinsignals_history.json")


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def media_kind(message: Any) -> str | None:
    media = getattr(message, "media", None)
    return type(media).__name__ if media is not None else None


def serialize_message(message: Any) -> dict[str, Any]:
    reply = getattr(message, "reply_to", None)
    return {
        "id": message.id,
        "date": iso(message.date),
        "edit_date": iso(getattr(message, "edit_date", None)),
        "text": message.message or "",
        "reply_to_msg_id": getattr(reply, "reply_to_msg_id", None),
        "grouped_id": getattr(message, "grouped_id", None),
        "post_author": getattr(message, "post_author", None),
        "views": getattr(message, "views", None),
        "forwards": getattr(message, "forwards", None),
        "media_type": media_kind(message),
    }


def prompt_hidden_password() -> str:
    script = (
        'display dialog "Ingresa tu contraseña 2FA de Telegram" '
        'default answer "" with hidden answer '
        'buttons {"Cancelar", "Continuar"} default button "Continuar" '
        'with title "NexUX · Telegram"'
    )
    result = subprocess.run(
        ["osascript", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    prefix = "button returned:Continuar, text returned:"
    if not result.startswith(prefix):
        raise RuntimeError("Telegram 2FA dialog did not return a password")
    return result[len(prefix) :]


async def authorize_with_qr(client: TelegramClient, qr_path: Path) -> None:
    if await client.is_user_authorized():
        return

    while True:
        login = await client.qr_login()
        qr_path.parent.mkdir(parents=True, exist_ok=True)
        qrcode.make(login.url).save(qr_path)
        os.chmod(qr_path, 0o600)
        print(f"QR_READY {qr_path}", flush=True)
        try:
            await login.wait(timeout=180)
            break
        except asyncio.TimeoutError:
            print("QR_EXPIRED regenerating", flush=True)
            continue
        except errors.SessionPasswordNeededError:
            password = prompt_hidden_password()
            await client.sign_in(password=password)
            break

    qr_path.unlink(missing_ok=True)


async def find_channel(client: TelegramClient, title: str) -> Any:
    wanted = title.strip().casefold()
    matches = []
    async for dialog in client.iter_dialogs():
        if dialog.name.strip().casefold() == wanted:
            matches.append(dialog.entity)
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one channel named {title!r}; found {len(matches)}"
        )
    return matches[0]


async def export_channel(args: argparse.Namespace) -> None:
    env = load_env_file(args.config)
    api_id = int(env["TELEGRAM_API_ID"])
    api_hash = env["TELEGRAM_API_HASH"]

    args.session.parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(str(args.session), api_id, api_hash)
    await client.connect()
    try:
        await authorize_with_qr(client, args.qr)
        entity = await find_channel(client, args.channel)
        messages = []
        async for message in client.iter_messages(entity, reverse=True):
            messages.append(serialize_message(message))
            if len(messages) % 1000 == 0:
                print(f"READ {len(messages)}", flush=True)

        payload = {
            "research_only": True,
            "source": "telegram_mtproto_user_api",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "channel": {"title": args.channel, "id": entity.id},
            "message_count": len(messages),
            "messages": messages,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temp = args.output.with_suffix(args.output.suffix + ".tmp")
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.chmod(temp, 0o600)
        temp.replace(args.output)
        print(f"DONE {len(messages)} {args.output}", flush=True)
    finally:
        await client.disconnect()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", default="Vip CoinSignals")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--session", type=Path, default=DEFAULT_SESSION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--qr",
        type=Path,
        default=Path.home() / ".config" / "nexux" / "telegram-login-qr.png",
    )
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(export_channel(parse_args()))
