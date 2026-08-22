"""Lectura fundamental explicable inspirada en la metodología estudiada.

No replica opiniones ni produce órdenes. Convierte estados CMF en gatillantes
auditables; valoración y precio siguen siendo requisitos para comprar/vender.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation


STRATEGY_VERSION = "inversor-chileno-rubric-0.1.0"
SOURCE_VIDEOS = [
    {"video_id": "Mu_U7yuQQCg", "role": "sell_discipline"},
    {"video_id": "drCHiopIUMM", "role": "valuation_and_margin_of_safety"},
    {"video_id": "l579eO5M89A", "role": "free_cash_flow"},
    {"video_id": "fiilug8lCUs", "role": "balance_quality"},
]


def _number(value):
    if value is None:
        return None
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return None


def _same_period_last_year(history: list[dict], period: str) -> dict | None:
    wanted = str(int(period) - 100)
    return next((item for item in history if item.get("period") == wanted), None)


def evaluate_observation(observation: dict, history: list[dict] | None = None) -> dict:
    history = history or []
    analysis = observation.get("analysis") or {}
    period = observation.get("period") or observation.get("latest_available_period")
    previous = _same_period_last_year(history, period) if period else None
    previous_analysis = (previous or {}).get("analysis") or {}
    growth = _number(analysis.get("revenue_growth_yoy"))
    op_margin = _number(analysis.get("operating_margin"))
    net_margin = _number(analysis.get("net_margin"))
    fcf = _number(analysis.get("free_cash_flow"))
    ocf = _number(analysis.get("operating_cash_flow"))
    leverage = _number(analysis.get("liabilities_to_assets"))
    coverage = _number(analysis.get("current_coverage"))
    conversion = _number(analysis.get("cash_conversion"))
    prior_margin = _number(previous_analysis.get("operating_margin"))

    positives, warnings, critical = [], [], []
    score = 50
    if growth is not None:
        if growth > 0.05:
            positives.append(f"ventas interanuales {growth:+.1%}")
            score += 10
        elif growth < 0:
            warnings.append(f"ventas interanuales {growth:+.1%}")
            score -= 12
        else:
            positives.append(f"ventas interanuales {growth:+.1%}")
            score += 4
    if op_margin is not None and op_margin > 0:
        positives.append(f"margen operacional positivo {op_margin:.1%}")
        score += 10 if op_margin >= 0.1 else 5
    elif op_margin is not None:
        critical.append(f"margen operacional {op_margin:.1%}")
        score -= 18
    if prior_margin is not None and op_margin is not None:
        delta = op_margin - prior_margin
        if delta < -0.02:
            warnings.append(f"margen operacional cae {abs(delta):.1%} interanual")
            score -= 10
        elif delta > 0.02:
            positives.append(f"margen operacional mejora {delta:.1%} interanual")
            score += 8
    if net_margin is not None and net_margin < 0:
        critical.append(f"margen neto negativo {net_margin:.1%}")
        score -= 18
    elif net_margin is not None:
        score += 8 if net_margin >= 0.05 else 3
    if ocf is not None:
        (positives if ocf > 0 else critical).append(
            "flujo operativo positivo" if ocf > 0 else "flujo operativo negativo")
        score += 8 if ocf > 0 else -18
    if fcf is not None:
        (positives if fcf > 0 else warnings).append(
            "flujo de caja libre positivo" if fcf > 0 else "flujo de caja libre negativo")
        score += 8 if fcf > 0 else -10
    if conversion is not None and conversion > 1:
        positives.append("flujo libre supera la utilidad contable")
        score += 4
    elif conversion is not None and conversion < 0:
        score -= 4
    if leverage is not None:
        if leverage > 0.85:
            critical.append(f"pasivos/activos elevado {leverage:.1%}")
            score -= 12
        elif leverage < 0.65:
            positives.append(f"pasivos/activos contenido {leverage:.1%}")
            score += 5
    if coverage is not None:
        if coverage < 1:
            warnings.append(f"cobertura corriente bajo 1x ({coverage:.2f}x)")
            score -= 8
        elif coverage >= 1.3:
            positives.append(f"cobertura corriente {coverage:.2f}x")
            score += 5

    measured = sum(value is not None for value in (
        growth, op_margin, net_margin, fcf, ocf, leverage, coverage, conversion))
    score = max(0, min(100, score))
    if critical or score < 40:
        view = "REVISAR TESIS"
    elif score >= 78 and measured >= 5:
        view = "FUNDAMENTOS FUERTES"
    else:
        view = "EN OBSERVACIÓN"
    return {
        "strategy_version": STRATEGY_VERSION,
        "period": period,
        "score": score,
        "data_points": measured,
        "confidence": "medium" if measured >= 5 else "low",
        "fundamental_view": view,
        "positive_factors": positives,
        "warning_factors": warnings,
        "critical_factors": critical,
        "portfolio_action_research": (
            "REVISAR / POSIBLE REDUCCIÓN" if view == "REVISAR TESIS" else
            "MANTENER / EVALUAR CON VALORACIÓN" if view == "FUNDAMENTOS FUERTES" else
            "MANTENER EN OBSERVACIÓN"
        ),
        "buy_sell_gate": "waiting_for_authorized_price_and_valuation",
        "buy_sell_recommendation": None,
        "methodology_status": "editorial_interpretation_not_financial_evidence",
        "youtube_feature_allowed": False,
        "source_videos": SOURCE_VIDEOS,
        "disclaimer": "lectura de investigación; no es una orden ni asesoría personalizada",
    }


def build_radar(dataset: dict, limit: int = 40, allowed_ruts: set[str] | None = None) -> dict:
    cmf = dataset.get("cmf") or {}
    sources = cmf.get("sources") or []
    comparable = next((item["period"] for item in sources if not item.get("partial")), None)
    comparable = comparable or (cmf.get("periods") or [None])[0]
    observations = [item for item in cmf.get("observations", [])
                    if item.get("period") == comparable
                    and (allowed_ruts is None or item.get("rut") in allowed_ruts)]
    all_history = cmf.get("observations", [])
    rows = []
    for item in observations:
        history = [other for other in all_history if other.get("rut") == item.get("rut")]
        reading = evaluate_observation(item, history)
        rows.append({
            "rut": item.get("rut"), "company": item.get("company"),
            "period": item.get("period"), "analysis": item.get("analysis"),
            "reading": reading,
        })
    rows.sort(key=lambda item: (item["reading"]["score"], item["company"]), reverse=True)
    return {
        "strategy_version": STRATEGY_VERSION, "period": comparable,
        "cross_section_comparable": True, "count": len(rows), "rows": rows[:limit],
        "recommendation_gate": "prices_and_valuation_required",
    }
