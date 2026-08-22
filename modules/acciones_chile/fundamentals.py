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
    "total_assets": ("Total de activos",),
    "total_liabilities": ("Total de pasivos",),
    "current_assets": ("Activos corrientes totales",),
    "current_liabilities": ("Pasivos corrientes totales",),
    "cash": ("Efectivo y equivalentes al efectivo",),
    "inventories": ("Inventarios corrientes",),
    "equity": ("Patrimonio total",),
    "operating_cash_flow": (
        "Flujos de efectivo netos procedentes de (utilizados en) actividades de operación",
    ),
    "capex_ppe": ("Compras de propiedades, planta y equipo",),
    "capex_intangibles": ("Compras de activos intangibles",),
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
    capex = sum((value or Decimal(0) for name, value in values.items()
                 if name in {"capex_ppe", "capex_intangibles"}), Decimal(0))
    free_cash_flow = (values["operating_cash_flow"] - capex
                      if values["operating_cash_flow"] is not None else None)
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
        "total_assets": str(values["total_assets"]) if values["total_assets"] is not None else None,
        "total_liabilities": (str(values["total_liabilities"])
                              if values["total_liabilities"] is not None else None),
        "current_assets": str(values["current_assets"]) if values["current_assets"] is not None else None,
        "current_liabilities": (str(values["current_liabilities"])
                                 if values["current_liabilities"] is not None else None),
        "cash": str(values["cash"]) if values["cash"] is not None else None,
        "inventories": str(values["inventories"]) if values["inventories"] is not None else None,
        "equity": str(values["equity"]) if values["equity"] is not None else None,
        "operating_cash_flow": (str(values["operating_cash_flow"])
                                if values["operating_cash_flow"] is not None else None),
        "capex": str(capex) if values["operating_cash_flow"] is not None else None,
        "free_cash_flow": str(free_cash_flow) if free_cash_flow is not None else None,
        "liabilities_to_assets": _ratio(values["total_liabilities"], values["total_assets"]),
        "current_coverage": _ratio(values["current_assets"], values["current_liabilities"]),
        "cash_conversion": _ratio(free_cash_flow, values["net_income"]),
        "source": "CMF IFRS TXT",
        "is_prediction": False,
    }
