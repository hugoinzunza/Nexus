"""Tests de auth — cubren la forja de sesión (A1 de la auditoría): un token de
`state` OAuth (que se entrega a usuarios anónimos en /auth/google) NO debe poder
usarse como cookie de sesión."""
import pytest


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
