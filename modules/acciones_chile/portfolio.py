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
        market_price = None
        if raw.get("market_price") not in (None, ""):
            try:
                market_price = Decimal(str(raw["market_price"]))
            except (InvalidOperation, TypeError) as exc:
                raise ValueError(f"holding {index}: precio de mercado inválido") from exc
            if market_price < 0:
                raise ValueError(f"holding {index}: precio de mercado negativo")
        initial_value = quantity * average_cost
        market_value = quantity * market_price if market_price is not None else None
        unrealized_pnl = market_value - initial_value if market_value is not None else None
        return_pct = (unrealized_pnl / initial_value
                      if unrealized_pnl is not None and initial_value else None)
        holding = {
            "ticker": ticker,
            "company_rut": rut or None,
            "quantity": str(quantity),
            "average_cost": str(average_cost),
            "currency": str(raw.get("currency") or "CLP").strip().upper(),
            "initial_value": str(initial_value),
            "market_price": str(market_price) if market_price is not None else None,
            "market_value": str(market_value) if market_value is not None else None,
            "unrealized_pnl": str(unrealized_pnl) if unrealized_pnl is not None else None,
            "return_pct": float(return_pct) if return_pct is not None else None,
        }
        holdings.append(holding)
    available_cash = None
    if payload.get("available_cash") not in (None, ""):
        try:
            available_cash = Decimal(str(payload["available_cash"]))
        except (InvalidOperation, TypeError) as exc:
            raise ValueError("saldo disponible inválido") from exc
        if available_cash < 0:
            raise ValueError("saldo disponible negativo")
    return {
        "source": str(payload.get("source") or "renta4_manual_export"),
        "as_of": payload.get("as_of"),
        "available_cash": str(available_cash) if available_cash is not None else None,
        "holdings": holdings,
        "read_only": True,
    }
