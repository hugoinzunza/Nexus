"""Smoke tests: que la app y sus piezas IMPORTEN y que el cifrado de la bóveda
funcione. Sin red, sin DB, sin servicios externos.

Corre en CI en el Python del VPS (3.14) y el de Railway → caza incompatibilidades
de versión como la de hoy (SQLAlchemy 2.0.36 rompía al importar en Python 3.14 y
tumbó el motor). Un simple `import core.app` lo habría detectado.
"""
import base64
import importlib

import pytest


def test_import_core_app():
    """Importa toda la app (corre Hub(load_config()) a nivel de módulo). Caza
    errores de import / incompatibilidades de dependencias."""
    importlib.import_module("core.app")


@pytest.mark.parametrize("mod", [
    "core.db", "core.auth", "core.store", "core.vault", "core.push",
    "modules.journal.module", "modules.journal.collector",
    "modules.journal.binance_client", "modules.journal.stats",
    "modules.trading.module", "modules.trading.news", "modules.trading.dashboard",
    "modules.trading.setups_store",
])
def test_import_module(mod):
    importlib.import_module(mod)


def test_vault_roundtrip():
    """Cifra credenciales con la pública y descífralas con la privada (envelope)."""
    from core import vault
    priv, pub = vault.generate_keypair()
    blob = vault.seal_credentials("APIKEY_abcdef123456", "SECRET_xyz9876543210", pub)
    assert "APIKEY_abcdef" not in str(blob), "fuga de plaintext en el sobre"
    k, s = vault.unseal_credentials(blob, priv)
    assert (k, s) == ("APIKEY_abcdef123456", "SECRET_xyz9876543210")


def test_vault_tamper_detected():
    """Un sobre alterado debe ser rechazado (AES-GCM autentica)."""
    from core import vault
    priv, pub = vault.generate_keypair()
    blob = vault.seal_credentials("a" * 20, "b" * 20, pub)
    raw = bytearray(base64.b64decode(blob["ct"]))
    raw[0] ^= 1
    blob["ct"] = base64.b64encode(bytes(raw)).decode()
    with pytest.raises(Exception):
        vault.unseal_credentials(blob, priv)


def test_vault_public_cannot_decrypt():
    """La clave pública NO puede descifrar (defensa en profundidad: Railway no descifra)."""
    from core import vault
    _, pub = vault.generate_keypair()
    blob = vault.seal_credentials("a" * 20, "b" * 20, pub)
    with pytest.raises(Exception):
        vault.unseal(blob, pub)
