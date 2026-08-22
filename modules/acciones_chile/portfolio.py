"""Contrato mínimo para importar una cartera personal de Renta 4."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation


MAX_HOLDINGS = 300


def normalize_portfolio(payload: dict) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("holdings"), list):
        raise ValueError("se esperaba un objeto con holdings[]")
    if len(payload["holdings"]) > MAX_HOLDINGS:
        raise ValueError("demasiadas posiciones")
    holdings = []
    for index, raw in enumerate(payload["holdings"]):
        if not isinstance(raw, dict):
            raise ValueError(f"holding {index}: formato inválido")
        ticker = str(raw.get("ticker") or "").strip().upper()
        if not ticker or len(ticker) > 20:
            raise ValueError(f"holding {index}: ticker inválido")
        try:
            quantity = Decimal(str(raw.get("quantity")))
            average_cost = Decimal(str(raw.get("average_cost")))
        except (InvalidOperation, TypeError) as exc:
            raise ValueError(f"holding {index}: cantidad o costo inválido") from exc
        if quantity < 0 or average_cost < 0:
            raise ValueError(f"holding {index}: no se aceptan valores negativos")
        rut = "".join(ch for ch in str(raw.get("company_rut") or "") if ch.isdigit())[:8]
        holdings.append({
            "ticker": ticker,
            "company_rut": rut or None,
            "quantity": str(quantity),
            "average_cost": str(average_cost),
            "currency": str(raw.get("currency") or "CLP").strip().upper(),
        })
    return {
        "source": str(payload.get("source") or "renta4_manual_export"),
        "as_of": payload.get("as_of"),
        "holdings": holdings,
        "read_only": True,
    }
