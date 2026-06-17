"""Autenticación multi-usuario de NexUX — Google OAuth2 + sesión por cookie firmada.

Diseño defensivo (igual filosofía que el resto del proyecto):
  - INERTE hasta configurarse: `enabled()` es True solo si están GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET y SESSION_SECRET (y hay DATABASE_URL). Sin eso, el sitio
    funciona como hoy — un solo usuario (tú, admin), todo abierto, sin login. Así
    se puede desplegar sin riesgo de quedar fuera; se enciende al poner las vars.
  - La cookie de sesión va FIRMADA (itsdangerous), no cifrada: no guarda secretos,
    solo {uid, email, role, name, picture}. La firma evita que se manipule.
  - El flujo OAuth2 se hace con urllib (stdlib): intercambio de code por token y
    lectura de userinfo. Sin SDK extra.
  - Beta CERRADA: solo el email admin o un email con invitación puede entrar.

No coloca ni modifica nada en exchanges; es identidad para gatear datos personales.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Optional

from core import db
from core.store import DEFAULT_EMAIL, DEFAULT_NAME

ADMIN_EMAIL = DEFAULT_EMAIL  # hugoinzunza@gmail.com — tú, CEO/admin
COOKIE = "nexux_session"
_MAX_AGE = 60 * 60 * 24 * 30  # 30 días

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


# --- Configuración / estado ------------------------------------------------
def _client_id() -> str:
    return os.environ.get("GOOGLE_CLIENT_ID", "").strip()


def _client_secret() -> str:
    return os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()


def _secret() -> str:
    return os.environ.get("SESSION_SECRET", "").strip()


def enabled() -> bool:
    """True solo si está todo configurado. Si no, la auth queda inerte."""
    return bool(_client_id() and _client_secret() and _secret() and db.database_enabled())


def redirect_uri(request_base: str) -> str:
    """URI de callback. Se puede fijar con OAUTH_REDIRECT_URI; si no, se deriva
    del host de la request (útil entre nexux.cl y previews)."""
    fixed = os.environ.get("OAUTH_REDIRECT_URI", "").strip()
    if fixed:
        return fixed
    return request_base.rstrip("/") + "/auth/callback"


# --- Cookie de sesión (firmada) --------------------------------------------
def _serializer():
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(_secret(), salt="nexux-session")


def make_cookie(user: dict) -> str:
    return _serializer().dumps({
        "uid": user.get("uid"), "email": user.get("email"),
        "role": user.get("role"), "name": user.get("name"),
        "picture": user.get("picture"),
    })


def _read_cookie(token: str) -> Optional[dict]:
    if not token:
        return None
    try:
        from itsdangerous import BadSignature, SignatureExpired
        try:
            return _serializer().loads(token, max_age=_MAX_AGE)
        except (BadSignature, SignatureExpired):
            return None
    except Exception:  # noqa: BLE001
        return None


def current_user(request) -> Optional[dict]:
    """Usuario actual. Con auth inerte → admin sintético (modo un-usuario, como
    hoy, sin tocar la DB). Con auth activa → lo que diga la cookie firmada."""
    if not enabled():
        return {"uid": None, "email": ADMIN_EMAIL, "role": "admin",
                "name": DEFAULT_NAME, "picture": None, "synthetic": True}
    try:
        token = request.cookies.get(COOKIE, "")
    except Exception:  # noqa: BLE001
        token = ""
    return _read_cookie(token)


def is_admin(user: Optional[dict]) -> bool:
    return bool(user and user.get("role") == "admin")


# --- Flujo OAuth2 con Google ----------------------------------------------
def login_url(state: str, cb_uri: str) -> str:
    params = {
        "client_id": _client_id(),
        "redirect_uri": cb_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return _AUTH_URL + "?" + urllib.parse.urlencode(params)


def sign_state(data: dict) -> str:
    return _serializer().dumps({"st": data})


def read_state(token: str) -> Optional[dict]:
    d = _read_cookie(token)  # mismo serializer/firma; corta vida implícita
    if isinstance(d, dict) and "st" in d:
        return d["st"]
    return None


def _post_form(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def exchange_code(code: str, cb_uri: str) -> dict:
    """Code → userinfo de Google ({sub, email, email_verified, name, picture})."""
    tok = _post_form(_TOKEN_URL, {
        "code": code, "client_id": _client_id(), "client_secret": _client_secret(),
        "redirect_uri": cb_uri, "grant_type": "authorization_code"})
    access = tok.get("access_token")
    if not access:
        raise RuntimeError("sin access_token de Google")
    req = urllib.request.Request(_USERINFO_URL, headers={"Authorization": f"Bearer {access}"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


# --- Política de acceso + alta de usuario ----------------------------------
def is_allowed(email: str) -> bool:
    """El admin siempre; el resto, solo con invitación (beta cerrada)."""
    email = (email or "").lower().strip()
    if not email:
        return False
    if email == ADMIN_EMAIL.lower():
        return True
    from sqlalchemy import select
    with db.session() as s:
        inv = s.scalar(select(db.Invitation).where(db.Invitation.email == email))
        return inv is not None


def list_invitations() -> list:
    """Invitaciones existentes (para el panel admin)."""
    from sqlalchemy import select
    with db.session() as s:
        rows = s.scalars(select(db.Invitation).order_by(db.Invitation.created_at.desc())).all()
        return [{"id": r.id, "email": r.email,
                 "created_at": r.created_at.isoformat() if r.created_at else None,
                 "used_at": r.used_at.isoformat() if r.used_at else None} for r in rows]


def add_invitation(email: str, by_uid: Optional[int]) -> dict:
    """Invita un email a la beta. Idempotente (no duplica). Devuelve {ok, error}."""
    email = (email or "").lower().strip()
    if "@" not in email or "." not in email.split("@")[-1]:
        return {"ok": False, "error": "email inválido"}
    if email == ADMIN_EMAIL.lower():
        return {"ok": False, "error": "el admin no necesita invitación"}
    from sqlalchemy import select
    with db.session() as s:
        exists = s.scalar(select(db.Invitation).where(db.Invitation.email == email))
        if exists:
            return {"ok": False, "error": "ya estaba invitado"}
        s.add(db.Invitation(email=email, invited_by=by_uid))
        return {"ok": True, "email": email}


def delete_invitation(inv_id: int) -> bool:
    from sqlalchemy import select
    with db.session() as s:
        inv = s.scalar(select(db.Invitation).where(db.Invitation.id == inv_id))
        if inv is None:
            return False
        s.delete(inv)
        return True


def list_users() -> list:
    """Usuarios registrados (para que el admin vea quién entró)."""
    from sqlalchemy import select
    with db.session() as s:
        rows = s.scalars(select(db.User).order_by(db.User.created_at.desc())).all()
        return [{"id": r.id, "email": r.email, "name": r.name, "role": r.role,
                 "picture": r.picture,
                 "last_login": r.last_login.isoformat() if r.last_login else None}
                for r in rows]


def upsert_user(userinfo: dict) -> dict:
    """Crea/actualiza el usuario tras un login válido y devuelve el dict de sesión.
    Marca la invitación como usada. Asigna rol admin al email admin."""
    from sqlalchemy import select
    email = (userinfo.get("email") or "").lower().strip()
    sub = userinfo.get("sub")
    name = userinfo.get("name") or email.split("@")[0]
    picture = userinfo.get("picture")
    role = "admin" if email == ADMIN_EMAIL.lower() else "beta"
    with db.session() as s:
        u = s.scalar(select(db.User).where(db.User.email == email))
        if u is None:
            u = db.User(email=email, name=name, role=role,
                        google_sub=sub, picture=picture, last_login=datetime.utcnow())
            s.add(u)
        else:
            u.name = name or u.name
            u.google_sub = sub or u.google_sub
            u.picture = picture or u.picture
            u.last_login = datetime.utcnow()
            if email == ADMIN_EMAIL.lower():
                u.role = "admin"
        s.flush()
        # Marcar invitación usada (si la hay y no es admin).
        if role != "admin":
            inv = s.scalar(select(db.Invitation).where(db.Invitation.email == email))
            if inv is not None and inv.used_at is None:
                inv.used_at = datetime.utcnow()
        return {"uid": u.id, "email": u.email, "role": u.role,
                "name": u.name, "picture": u.picture}
