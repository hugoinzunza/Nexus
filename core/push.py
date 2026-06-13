"""Web push para Nexus — preparado para alertas futuras.

Mismo patrón que apps/proteq-hub de ClaudeOS (pywebpush + claves VAPID), pero
simplificado: las suscripciones se guardan en un archivo JSON local
(`data/push_subs.json`) en vez de una base de datos, porque Nexus todavía no
tiene una.

Las ALERTAS en sí (precio objetivo, cruces de momentum, etc.) se implementan más
adelante. Acá dejamos lista la cañería: registrar el navegador/celular y poder
enviarle una notificación con `enviar_push(...)`.

Variables de entorno (se configuran en Railway cuando activemos alertas):
  VAPID_PUBLIC_KEY_B64   Clave pública en base64url (la que va al frontend).
  VAPID_PRIVATE_KEY_B64  Clave privada (32 bytes raw en base64url, recomendado).
  VAPID_SUBJECT          mailto:tu@correo  (identifica al servidor).

Generar un par de claves VAPID (una sola vez):
  pip install py-vapid && vapid --gen   # o con la consola de web-push
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from typing import Optional

_LOCK = threading.Lock()
_SUBS_PATH: Optional[str] = None
_LOG = print


def init(root: str, log=print) -> None:
    """Configura dónde se guardan las suscripciones. Lo llama el lifespan."""
    global _SUBS_PATH, _LOG
    _LOG = log
    from core.paths import persist_dir
    data_dir = persist_dir(root)   # volumen de Railway si hay → persiste deploys
    _SUBS_PATH = os.path.join(data_dir, "push_subs.json")
    if not os.path.isfile(_SUBS_PATH):
        _write_all([])


# --- Configuración VAPID -------------------------------------------------
def public_key_b64() -> str:
    return os.environ.get("VAPID_PUBLIC_KEY_B64", "").strip()


def configurado() -> bool:
    return bool(public_key_b64() and os.environ.get("VAPID_PRIVATE_KEY_B64"))


def _vapid_claims() -> dict:
    return {"sub": os.environ.get("VAPID_SUBJECT", "mailto:hugo@nexus.local")}


def _private_key_pem() -> str:
    """Convierte VAPID_PRIVATE_KEY_B64 (32 bytes raw en base64url) a PEM PKCS8,
    que es lo que espera pywebpush."""
    raw_b64 = os.environ.get("VAPID_PRIVATE_KEY_B64", "").strip()
    if not raw_b64:
        return ""
    import base64
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    padded = raw_b64 + "=" * (-len(raw_b64) % 4)
    priv_int = int.from_bytes(base64.urlsafe_b64decode(padded), "big")
    priv = ec.derive_private_key(priv_int, ec.SECP256R1())
    return priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


# --- Almacén de suscripciones (archivo JSON) -----------------------------
def _read_all() -> list:
    if not _SUBS_PATH or not os.path.isfile(_SUBS_PATH):
        return []
    try:
        with open(_SUBS_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return []


def _write_all(subs: list) -> None:
    if not _SUBS_PATH:
        return
    with open(_SUBS_PATH, "w", encoding="utf-8") as fh:
        json.dump(subs, fh, ensure_ascii=False, indent=2)


def guardar_suscripcion(sub: dict) -> int:
    """Guarda (o actualiza) una suscripción del navegador. Devuelve el total."""
    endpoint = sub.get("endpoint", "")
    if not endpoint:
        return len(_read_all())
    with _LOCK:
        subs = _read_all()
        subs = [s for s in subs if s.get("endpoint") != endpoint]
        sub["_creada"] = datetime.utcnow().isoformat() + "Z"
        subs.append(sub)
        _write_all(subs)
        _LOG(f"push: suscripción guardada (total {len(subs)})")
        return len(subs)


def borrar_suscripcion(endpoint: str) -> int:
    with _LOCK:
        subs = [s for s in _read_all() if s.get("endpoint") != endpoint]
        _write_all(subs)
        return len(subs)


# --- Envío (se usará cuando lleguen las alertas) -------------------------
def enviar_push(sub: dict, payload: dict) -> tuple[bool, str]:
    """Envía un push a una suscripción concreta. Devuelve (ok, mensaje_error)."""
    if not configurado():
        return False, "VAPID no configurado"
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        return False, "pywebpush no instalado"

    sub_info = {
        "endpoint": sub.get("endpoint"),
        "keys": sub.get("keys", {}),
    }
    try:
        webpush(
            subscription_info=sub_info,
            data=json.dumps(payload),
            vapid_private_key=_private_key_pem(),
            vapid_claims=_vapid_claims(),
            ttl=3600 * 24,
        )
        return True, ""
    except WebPushException as exc:  # noqa: BLE001
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):  # suscripción vencida → la quitamos
            borrar_suscripcion(sub.get("endpoint", ""))
        return False, f"WebPushException HTTP={status}: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def notificar(title: str, body: str, url: str = "/", tag: Optional[str] = None) -> tuple[int, list]:
    """Envía una notificación a TODAS las suscripciones activas. Devuelve
    (enviados, errores). Punto de entrada para las futuras alertas."""
    payload = {"title": title, "body": body, "url": url, "tag": tag or "nexus"}
    enviados, errores = 0, []
    for sub in _read_all():
        ok, err = enviar_push(sub, payload)
        if ok:
            enviados += 1
        elif err:
            errores.append(err)
    return enviados, errores
