"""Lectura fundamental explicable inspirada en la metodología estudiada.

No replica opiniones ni produce órdenes. Convierte estados CMF en gatillantes
auditables; valoración y precio siguen siendo requisitos para comprar/vender.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .fx import validate_eps_unit_record


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


def evaluate_valuation(history: list[dict], market_price, fx_rate: dict | None = None,
                       eps_unit_verification: dict | None = None,
                       issuer_rut: str | None = None) -> dict:
    """Calcula sólo múltiplos compatibles; no inventa precio justo."""
    price = _number(market_price)
    annual = next((item for item in sorted(history, key=lambda row: row.get("period", ""), reverse=True)
                   if str(item.get("period", "")).endswith("12")), None)
    analysis = (annual or {}).get("analysis") or {}
    eps = _number(analysis.get("basic_eps"))
    currency = (annual or {}).get("currency") or analysis.get("currency")
    result = {
        "market_price": price, "annual_period": (annual or {}).get("period"),
        "annual_eps": eps, "reporting_currency": currency,
        "pe": None, "fair_multiple": None, "fair_value": None,
        "margin_of_safety": None, "buy_sell_recommendation": None,
        "fx_rate": fx_rate, "eps_unit_verification": eps_unit_verification,
    }
    if price is None:
        result["status"] = "waiting_for_authorized_market_price"
    elif annual is None or eps is None:
        result["status"] = "annual_eps_unavailable"
    elif currency not in {"CLP", "USD"}:
        result["status"] = "reporting_currency_not_supported"
    else:
        verification = eps_unit_verification or {}
        expected_unit = f"{currency}_PER_SHARE"
        try:
            validate_eps_unit_record(str(issuer_rut or ""), verification)
            evidence_valid = (
                verification.get("period") == annual.get("period") and
                verification.get("unit") == expected_unit and
                abs((_number(verification.get("cmf_value")) or 0) - eps) <= 0.0000001
            )
        except ValueError:
            evidence_valid = False
        if not evidence_valid:
            result["status"] = "eps_unit_verification_required"
        elif currency == "USD" and (
                not fx_rate or _number(fx_rate.get("clp_per_usd")) is None):
            result["status"] = "official_fx_rate_required"
        else:
            source_eps = _number(verification["reported_value"])
            converted_eps = source_eps
            if currency == "USD":
                converted_eps *= _number(fx_rate.get("clp_per_usd")) or 0
            result["cmf_eps_raw"] = eps
            result["cmf_value_multiplier"] = _number(
                verification.get("cmf_value_multiplier"))
            result["eps_verified_per_share"] = source_eps
            result["eps_verified_unit"] = expected_unit
            result["eps_clp_per_share"] = round(converted_eps, 8)
            if converted_eps <= 0:
                result["status"] = "pe_not_meaningful_for_nonpositive_eps"
            else:
                result["pe"] = round(price / converted_eps, 4)
                result["status"] = "observed_multiple_ready_fair_value_pending"
    result["gate"] = "sector_fair_multiple_and_margin_of_safety_required"
    return result


def evaluate_decision_evidence(reading: dict | None, valuation: dict | None,
                               events: dict | None, allocation_pct,
                               data_source_gate: dict | None = None) -> dict:
    """Explica el gate de decisión; nunca convierte una brecha en una orden."""
    reading, valuation, events = reading or {}, valuation or {}, events or {}
    allocation = _number(allocation_pct)
    checks = [
        {"key": "market_price", "label": "precio de mercado autorizado",
         "ready": valuation.get("market_price") is not None},
        {"key": "latest_result", "label": "último resultado detectado",
         "ready": events.get("statement_status") == "latest_period_detected"},
        {"key": "fundamentals", "label": "fundamentales suficientes",
         "ready": int(reading.get("data_points") or 0) >= 5},
        {"key": "observed_multiple", "label": "múltiplo observado compatible",
         "ready": valuation.get("pe") is not None},
        {"key": "fair_value", "label": "valor justo sustentado",
         "ready": valuation.get("fair_value") is not None},
        {"key": "margin_of_safety", "label": "margen de seguridad",
         "ready": valuation.get("margin_of_safety") is not None},
    ]
    blockers = [check["label"] for check in checks if not check["ready"]]
    if data_source_gate and data_source_gate.get("status") != "ready":
        blockers.append(data_source_gate.get("label") or "fuente contable requerida")
    warnings = []
    if allocation is not None and allocation >= 0.5:
        warnings.append(f"concentración elevada en cartera ({allocation:.1%})")
    if events.get("essential_notices_30d"):
        warnings.append(f"{events['essential_notices_30d']} hecho(s) esencial(es) en 30 días")
    ready_count = sum(check["ready"] for check in checks)
    return {
        "strategy_version": STRATEGY_VERSION,
        "operational_state": "blocked" if blockers else "ready_for_human_review",
        "checks_ready": ready_count,
        "checks_total": len(checks),
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
        "fundamental_view": reading.get("fundamental_view"),
        "research_posture": reading.get("portfolio_action_research"),
        "data_source_gate": data_source_gate,
        "buy_recommendation": None,
        "sell_recommendation": None,
        "orders": "prohibited",
    }


def portfolio_concentration(holdings: list[dict]) -> dict:
    """Mide concentración de la valorización; no prescribe rebalanceos."""
    weighted = [(item.get("ticker"), _number(item.get("allocation_pct"))) for item in holdings]
    weighted = [(ticker, weight) for ticker, weight in weighted if weight is not None]
    if not weighted:
        return {"status": "unavailable", "largest_ticker": None, "largest_weight": None,
                "hhi": None, "effective_positions": None, "level": None}
    largest_ticker, largest_weight = max(weighted, key=lambda item: item[1])
    hhi = sum(weight * weight for _, weight in weighted)
    if largest_weight >= 0.5 or hhi >= 0.35:
        level = "high"
    elif largest_weight >= 0.35 or hhi >= 0.25:
        level = "medium"
    else:
        level = "low"
    return {
        "status": "ready", "largest_ticker": largest_ticker,
        "largest_weight": round(largest_weight, 8), "hhi": round(hhi, 8),
        "effective_positions": round(1 / hhi, 4) if hhi else None,
        "level": level, "recommendation": None,
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
