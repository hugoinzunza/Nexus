"""Parser de eventos estructurados del bot HechosEsencialesChile.

Se ignora toda conversación humana. La disponibilidad causal es la fecha del
mensaje de Telegram, aunque el documento declare una hora de emisión anterior.
"""
from __future__ import annotations

import re
from typing import Any


SOURCE = "telegram:hechosesencialeschile"
FIELD = re.compile(r"(?:^|\s)[🏢🗓📅📂📄📊]\s*([^:]+?)\s*:\s*(.*?)(?=\s[🏢🗓📅📂📄📊]\s*[^:]+?\s*:|$)")


def parse_event(message_id: int, message_date: str, text: str) -> dict[str, Any] | None:
    normalized = " ".join((text or "").split())
    if "NUEVO ESTADO FINANCIERO" in normalized:
        event_type = "financial_statement"
    elif "NUEVO COMUNICADO ESENCIAL" in normalized:
        event_type = "essential_notice"
    else:
        return None
    fields = {key.strip().casefold(): value.strip() for key, value in FIELD.findall(normalized)}
    company = fields.get("empresa")
    if not company:
        return None
    event = {
        "source": SOURCE,
        "message_id": int(message_id),
        "event_type": event_type,
        "company": company,
        "available_at": message_date,
        "causal_timestamp": "telegram_message_date",
    }
    if event_type == "financial_statement":
        event.update({
            "period": fields.get("periodo"),
            "reported_emission_local": fields.get("fecha emisión"),
            "balance_type": fields.get("tipo balance"),
        })
    else:
        event.update({
            "reported_notice_local": fields.get("fecha"),
            "subject": fields.get("materia"),
        })
    return event
