"""Tests de auth — cubren la forja de sesión (A1 de la auditoría): un token de
`state` OAuth (que se entrega a usuarios anónimos en /auth/google) NO debe poder
usarse como cookie de sesión."""
import pytest
from fastapi.testclient import TestClient
from types import SimpleNamespace


@pytest.fixture
def auth(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-secret-para-tests")
    from core import auth as a
    return a


def test_state_token_no_forja_sesion(auth):
    state = auth.sign_state({"next": "/m/journal/"})
    # El token de state NO se lee como sesión (salt distinto + exige email).
    assert auth._read_cookie(state) is None
    # Pero SÍ se lee como state.
    assert auth.read_state(state) == {"next": "/m/journal/"}


def test_sesion_legitima_valida(auth):
    cookie = auth.make_cookie({"uid": 7, "email": "hugo@x.com", "role": "admin"})
    u = auth._read_cookie(cookie)
    assert u and u.get("email") == "hugo@x.com" and u.get("uid") == 7
    # Una cookie de sesión NO es un state válido.
    assert auth.read_state(cookie) is None


def test_payload_sin_email_rechazado(auth):
    # Firmado con el serializer de sesión pero sin email → no es sesión válida.
    firmado = auth._serializer().dumps({"st": {"x": 1}})
    assert auth._read_cookie(firmado) is None


def test_account_page_disponible_en_modo_local(monkeypatch):
    from core import app
    monkeypatch.setattr(app.auth, "enabled", lambda: False)
    response = TestClient(app.app).get("/account")
    assert response.status_code == 200
    assert "Mi cuenta" in response.text
    assert "/m/journal/api/connect-exchange" in response.text


def test_actualizar_perfil_renueva_cookie(monkeypatch):
    from core import app
    session_user = {"uid": 7, "email": "ana@example.com", "role": "beta",
                    "name": "Ana", "picture": None}
    monkeypatch.setattr(app.auth, "enabled", lambda: True)
    monkeypatch.setattr(app.auth, "current_user", lambda request: session_user)
    monkeypatch.setattr(app.auth, "update_profile", lambda uid, name: {
        **session_user, "name": name})
    monkeypatch.setattr(app.auth, "make_cookie", lambda user: "cookie-renovada")
    response = TestClient(app.app).put("/api/account/profile", json={"name": "Ana Torres"})
    assert response.status_code == 200
    assert response.json()["user"]["name"] == "Ana Torres"
    assert "nexux_session=cookie-renovada" in response.headers["set-cookie"]


def test_actualizar_perfil_rechaza_nombre_vacio(monkeypatch):
    from core import app
    monkeypatch.setattr(app.auth, "enabled", lambda: True)
    monkeypatch.setattr(app.auth, "current_user", lambda request: {
        "uid": 7, "email": "ana@example.com", "role": "beta"})
    response = TestClient(app.app).put("/api/account/profile", json={"name": "   "})
    assert response.status_code == 400


def test_bot_web_es_solo_admin(monkeypatch):
    from core import app
    request = SimpleNamespace(url=SimpleNamespace(path="/m/bot/"))
    monkeypatch.setattr(app.auth, "enabled", lambda: True)
    monkeypatch.setattr(app.auth, "current_user", lambda request: {
        "uid": 8, "email": "beta@example.com", "role": "beta"})
    blocked = app._gate("bot", request)
    assert blocked.status_code == 307
    # El rebote va a la casa del usuario, no a un módulo cripto cualquiera.
    assert blocked.headers["location"] == "/inicio"

    monkeypatch.setattr(app.auth, "current_user", lambda request: {
        "uid": 1, "email": "admin@example.com", "role": "admin"})
    assert app._gate("bot", request) is None
    assert ("bot", "ingest") in app._TOKEN_AUTH_POSTS
    assert ("coinglass", "visual-ingest") in app._TOKEN_AUTH_POSTS
    assert ("coinsignals", "ingest") in app._TOKEN_AUTH_POSTS
    assert ("journal", "ingest") in app._TOKEN_AUTH_POSTS
    assert ("acciones_chile", "ingest-portfolio") not in app._TOKEN_AUTH_POSTS
    assert ("acciones_chile", "ingest-telegram-events") in app._TOKEN_AUTH_POSTS


def test_acciones_chile_exige_sesion(monkeypatch):
    from core import app

    class FakeAccionesChile:
        def sse(self, subpath, query, user=None):
            return None

        def api(self, subpath, query, user=None):
            return (200, "application/json", b'{"ok":true}')

    request = SimpleNamespace(url=SimpleNamespace(path="/m/acciones_chile/api/events"))
    monkeypatch.setitem(app.hub.modules_by_slug, "acciones_chile", FakeAccionesChile())
    monkeypatch.setattr(app.auth, "enabled", lambda: True)
    monkeypatch.setattr(app.auth, "current_user", lambda request: None)
    blocked = app._gate("acciones_chile", request)
    assert blocked.status_code == 401
    response = TestClient(app.app).get("/m/acciones_chile/api/events")
    assert response.status_code == 401


def test_admin_puede_designar_otro_admin(monkeypatch):
    from core import app
    actor = {"uid": 1, "email": "owner@example.com", "role": "admin"}
    monkeypatch.setattr(app.auth, "enabled", lambda: True)
    monkeypatch.setattr(app.auth, "current_user", lambda request: actor)
    monkeypatch.setattr(app.auth, "set_user_role", lambda uid, role, actor_uid: {
        "ok": True, "user": {"id": uid, "email": "socio@example.com", "role": role}})
    response = TestClient(app.app).patch("/api/admin/users/9/role", json={"role": "admin"})
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "admin"


def test_ingesta_token_no_exige_cookie_pero_comandos_si(monkeypatch):
    from core import app

    class FakeBot:
        def api_post(self, subpath, body, headers, user=None):
            return (200, "application/json", b'{"ok":true}')

    monkeypatch.setitem(app.hub.modules_by_slug, "bot", FakeBot())
    monkeypatch.setitem(app.hub.modules_by_slug, "coinglass", FakeBot())
    monkeypatch.setitem(app.hub.modules_by_slug, "coinsignals", FakeBot())
    monkeypatch.setattr(app.auth, "enabled", lambda: True)
    monkeypatch.setattr(app.auth, "current_user", lambda request: None)
    client = TestClient(app.app)
    assert client.post("/m/bot/api/ingest", json={"ts": 1}).status_code == 200
    assert client.post(
        "/m/coinglass/api/visual-ingest",
        json={"research_only": True},
    ).status_code == 200
    assert client.post(
        "/m/coinsignals/api/ingest",
        json={"research_only": True},
    ).status_code == 200
    assert client.post("/m/bot/api/command", json={"action": "kill"}).status_code == 401


def test_next_de_login_rechaza_destinos_externos():
    """`startswith("/")` no basta: `//host` es protocolo-relativo y sale del sitio.

    Regresión de la auditoría de UX (SEC-01): el destino por defecto del login
    pasó a /inicio y con él se revisó el saneamiento de `next`.
    """
    from core.app import _safe_next, HOME

    for externo in ("//evil.example", "///evil.example", "/\\evil.example",
                    "https://evil.example", "http:/evil.example",
                    "javascript:alert(1)", "", None, 7):
        assert _safe_next(externo) == HOME, externo

    for interno in ("/inicio", "/m/trading/", "/m/acciones_chile/",
                    "/m/journal/?tab=hoy", "/account"):
        assert _safe_next(interno) == interno, interno


def test_inicio_exige_sesion_cuando_la_auth_esta_activa(monkeypatch):
    from core import app

    monkeypatch.setattr(app.auth, "enabled", lambda: True)
    monkeypatch.setattr(app.auth, "current_user", lambda request: None)
    bloqueado = app.inicio_page(SimpleNamespace(url=SimpleNamespace(path="/inicio")))
    assert bloqueado.status_code == 307
    assert bloqueado.headers["location"] == "/login?next=/inicio"

    monkeypatch.setattr(app.auth, "current_user", lambda request: {"uid": 1, "role": "admin"})
    servido = app.inicio_page(SimpleNamespace(url=SimpleNamespace(path="/inicio")))
    assert servido.status_code == 200
    assert "Acciones Chile" in servido.body.decode("utf-8")
