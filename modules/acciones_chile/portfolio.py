"""Contrato mínimo para importar una cartera personal de Renta 4."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re


MAX_HOLDINGS = 300
# Tope holgado pero finito: una cartera personal en pesos no se acerca a esto,
# y sin él `Infinity` y `1e999999` entraban como cantidades válidas.
MAX_MAGNITUD = Decimal("1e15")
ALLOWED_SOURCES = {
    "renta4_manual_export", "renta4_manual", "renta4_authenticated_web_snapshot",
}


def _decimal_acotado(valor, etiqueta: str) -> Decimal:
    """Decimal finito, no negativo y dentro de rango, o ValueError.

    `Decimal("NaN")` se construye sin error y sólo explota al comparar, así que
    la comprobación de finitud tiene que ser explícita.
    """
    try:
        numero = Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{etiqueta} inválido") from exc
    if not numero.is_finite():
        raise ValueError(f"{etiqueta} debe ser un número finito")
    if numero < 0:
        raise ValueError(f"{etiqueta} no puede ser negativo")
    if numero > MAX_MAGNITUD:
        raise ValueError(f"{etiqueta} fuera de rango")
    return numero


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
            quantity = _decimal_acotado(raw.get("quantity"), "cantidad")
            average_cost = _decimal_acotado(raw.get("average_cost"), "costo promedio")
        except ValueError as exc:
            raise ValueError(f"holding {index}: {exc}") from exc
        rut = "".join(ch for ch in str(raw.get("company_rut") or "") if ch.isdigit())[:8]
        market_price = None
        if raw.get("market_price") not in (None, ""):
            try:
                market_price = _decimal_acotado(raw["market_price"], "precio de mercado")
            except ValueError as exc:
                raise ValueError(f"holding {index}: {exc}") from exc
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
    ruts = [h["company_rut"] for h in holdings if h["company_rut"]]
    if len(set(ruts)) != len(ruts):
        raise ValueError("hay dos posiciones en la misma sociedad")
    sin_rut = [h["ticker"] for h in holdings if not h["company_rut"]]
    if len(set(sin_rut)) != len(sin_rut):
        raise ValueError("hay dos posiciones con el mismo ticker")
    available_cash = None
    if payload.get("available_cash") not in (None, ""):
        available_cash = _decimal_acotado(payload["available_cash"], "saldo disponible")
    source = str(payload.get("source") or "renta4_manual_export")
    if source not in ALLOWED_SOURCES:
        raise ValueError("fuente de cartera no permitida")
    as_of = payload.get("as_of")
    if as_of not in (None, "") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(as_of)):
        raise ValueError("fecha de cartera inválida")
    return {
        "source": source,
        "as_of": as_of or None,
        "available_cash": str(available_cash) if available_cash is not None else None,
        "holdings": holdings,
        "read_only": True,
    }
