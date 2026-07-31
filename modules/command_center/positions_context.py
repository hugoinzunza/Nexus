"""Proyeccion compacta y read-only de posiciones Binance ya recolectadas."""

from __future__ import annotations

import math
import time
from typing import Callable


def _number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _position(raw: dict) -> dict | None:
    if not isinstance(raw, dict) or not raw.get("symbol"):
        return None
    quantity = _number(raw.get("qty", raw.get("size")))
    entry = _number(raw.get("entry", raw.get("entryPrice")))
    mark = _number(raw.get("mark", raw.get("markPrice")))
    pnl = _number(
        raw.get(
            "unrealized_pnl",
            raw.get("unrealized", raw.get("unRealizedProfit")),
        )
    )
    leverage = _number(raw.get("leverage"))
    margin = _number(raw.get("margin", raw.get("margin_used")))
    if margin is None and quantity and mark and leverage:
        margin = abs(quantity * mark) / leverage
    roe = pnl / margin * 100 if pnl is not None and margin else None
    side = str(raw.get("side") or raw.get("position_side") or "").upper()
    if side not in {"LONG", "SHORT"}:
        amount = _number(raw.get("positionAmt"))
        side = "SHORT" if amount is not None and amount < 0 else "LONG"
    return {
        "symbol": str(raw["symbol"])[:24],
        "side": side,
        "quantity": abs(quantity) if quantity is not None else None,
        "entry": entry,
        "mark": mark,
        "pnl": pnl,
        "roe": roe,
        "leverage": leverage,
    }


def _positions(rows) -> list[dict]:
    result = [_position(row) for row in rows if isinstance(row, dict)]
    return sorted(
        (row for row in result if row is not None),
        key=lambda row: row["pnl"] if row["pnl"] is not None else 0,
    )


def _balance(source: dict) -> dict:
    return {
        "wallet": _number(source.get("wallet", source.get("balance"))),
        "available": _number(source.get("available")),
        "unrealized": _number(
            source.get("unrealized", source.get("upnl", source.get("unrealized_pnl")))
        ),
    }


class PositionsContextService:
    """Combina Diario y Bot sin acceder a credenciales ni enviar comandos."""

    def __init__(self, clock_ms: Callable[[], int] | None = None):
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))

    def project(
        self,
        journal: dict | None,
        bot: dict | None,
    ) -> dict:
        principal = self._principal(journal)
        bot_account = self._bot(bot)
        states = {principal["state"], bot_account["state"]}
        if "failed" in states:
            state = "degraded"
        elif "stale" in states or "unavailable" in states:
            state = "degraded"
        else:
            state = "ready"
        return {
            "generated_at_ms": self._clock_ms(),
            "state": state,
            "read_only": True,
            "accounts": [principal, bot_account],
            "total_positions": sum(
                len(account["positions"])
                for account in (principal, bot_account)
            ),
        }

    @staticmethod
    def _principal(source: dict | None) -> dict:
        if not isinstance(source, dict) or not source.get("has_data"):
            return PositionsContextService._empty_account(
                "principal", "Cuenta principal", "unavailable", "Sin datos del Diario"
            )
        futures = source.get("futures")
        if not isinstance(futures, dict) or not futures.get("ok"):
            return PositionsContextService._empty_account(
                "principal", "Cuenta principal", "failed", "Binance no disponible"
            )
        age = _number(source.get("age_seconds"))
        state = "stale" if age is not None and age > 180 else "ready"
        positions = _positions(futures.get("open_positions") or [])
        return {
            "id": "principal",
            "label": "Cuenta principal",
            "environment": "live",
            "state": state,
            "detail": "Datos antiguos" if state == "stale" else None,
            "age_seconds": age,
            "balance": _balance(futures.get("balance") or {}),
            "positions": positions,
            "total_pnl": sum(row["pnl"] or 0 for row in positions),
        }

    @staticmethod
    def _bot(source: dict | None) -> dict:
        if not isinstance(source, dict):
            return PositionsContextService._empty_account(
                "bot", "Cuenta Bot", "unavailable", "Sin snapshot del Bot"
            )
        if (
            source.get("source") == "local"
            and not source.get("positions")
            and not source.get("account")
            and not source.get("testnet")
        ):
            return PositionsContextService._empty_account(
                "bot", "Cuenta Bot", "unavailable", "Sin snapshot del VPS"
            )
        selected = source
        environment = "live" if source.get("live") else "dry-run"
        testnet = source.get("testnet")
        if (
            isinstance(testnet, dict)
            and not (source.get("positions") or [])
            and (testnet.get("positions") or testnet.get("account"))
        ):
            selected = testnet
            environment = "testnet"
        age = _number(source.get("age_seconds"))
        state = "stale" if age is not None and age > 90 else "ready"
        positions = _positions(selected.get("positions") or [])
        return {
            "id": "bot",
            "label": "Cuenta Bot",
            "environment": environment,
            "state": state,
            "detail": "Datos antiguos" if state == "stale" else None,
            "age_seconds": age,
            "balance": _balance(selected.get("account") or {}),
            "positions": positions,
            "total_pnl": sum(row["pnl"] or 0 for row in positions),
        }

    @staticmethod
    def _empty_account(
        account_id: str,
        label: str,
        state: str,
        detail: str,
    ) -> dict:
        return {
            "id": account_id,
            "label": label,
            "environment": "unknown",
            "state": state,
            "detail": detail,
            "age_seconds": None,
            "balance": _balance({}),
            "positions": [],
            "total_pnl": 0.0,
        }
