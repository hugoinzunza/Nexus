"""Métricas fundamentales explicables; no son recomendación ni señal."""
from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from .cmf import CMFRow


ACCOUNT_ALIASES = {
    "revenue": ("Ingresos de actividades ordinarias", "Ingresos ordinarios"),
    "operating_profit": (
        "Ganancias (pérdidas) de actividades operacionales",
        "Ganancia (pérdida) de actividades operacionales",
    ),
    "net_income": ("Ganancia (pérdida)",),
}


def _find(rows: Iterable[CMFRow], aliases: tuple[str, ...]) -> Decimal | None:
    candidates = [row.value for row in rows if row.account in aliases]
    return candidates[0] if candidates else None


def _ratio(numerator: Decimal | None, denominator: Decimal | None) -> float | None:
    if numerator is None or denominator in (None, Decimal(0)):
        return None
    return round(float(numerator / denominator), 6)


def analyze_company(current: Iterable[CMFRow], previous: Iterable[CMFRow] = ()) -> dict:
    current = list(current)
    previous = list(previous)
    if not current:
        return {"available": False, "reason": "sin filas CMF para la sociedad"}
    values = {name: _find(current, aliases) for name, aliases in ACCOUNT_ALIASES.items()}
    old = {name: _find(previous, aliases) for name, aliases in ACCOUNT_ALIASES.items()}
    return {
        "available": True,
        "period": current[0].period,
        "rut": current[0].rut,
        "company": current[0].company,
        "currency": current[0].currency,
        "revenue": str(values["revenue"]) if values["revenue"] is not None else None,
        "operating_profit": str(values["operating_profit"]) if values["operating_profit"] is not None else None,
        "net_income": str(values["net_income"]) if values["net_income"] is not None else None,
        "revenue_growth_yoy": _ratio(
            None if values["revenue"] is None or old["revenue"] is None else values["revenue"] - old["revenue"],
            old["revenue"],
        ),
        "operating_margin": _ratio(values["operating_profit"], values["revenue"]),
        "net_margin": _ratio(values["net_income"], values["revenue"]),
        "source": "CMF IFRS TXT",
        "is_prediction": False,
    }
