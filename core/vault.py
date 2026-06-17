"""Bóveda: cifrado de sobre (envelope encryption) para las llaves de exchange.

Diseño (defensa en profundidad, ver docs/PRODUCTO_NEXUX.md §8):
  - Una **KEK** (Key Encryption Key) asimétrica RSA-3072. La clave PÚBLICA vive en
    Railway (env `NEXUX_KEK_PUBLIC`); la PRIVADA vive SOLO en el VPS
    (env `NEXUX_KEK_PRIVATE` o `~/.nexus/kek_private.pem`, chmod 600).
  - Al conectar, la web genera una **data-key** AES-256 aleatoria, cifra las
    credenciales con AES-256-GCM, y "envuelve" la data-key con la pública (RSA-OAEP).
    Railway guarda solo el sobre → NO puede descifrar (no tiene la privada).
  - El colector (VPS) desenvuelve la data-key con la privada y descifra en memoria.

REGLA: las credenciales en claro nunca se loguean, ni se escriben a disco, ni se
devuelven al frontend. Solo viven en memoria el tiempo justo (cifrar / usar).
"""
from __future__ import annotations

import base64
import json
import os
from typing import Optional, Tuple

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_OAEP = padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                     algorithm=hashes.SHA256(), label=None)


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _ub64(s: str) -> bytes:
    return base64.b64decode(s)


# --- Generación de la KEK (uso único, setup) -----------------------------
def generate_keypair() -> Tuple[str, str]:
    """Devuelve (private_pem, public_pem). La privada va al VPS; la pública a Railway."""
    priv = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    private_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()).decode("ascii")
    public_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")
    return private_pem, public_pem


# --- Cifrar / descifrar ---------------------------------------------------
def seal(plaintext: bytes, public_pem: str) -> dict:
    """Cifra `plaintext` con una data-key AES-256-GCM nueva, envuelta por la KEK
    pública. Devuelve el sobre (JSON-serializable)."""
    pub = serialization.load_pem_public_key(public_pem.encode("ascii"))
    data_key = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    ct = AESGCM(data_key).encrypt(nonce, plaintext, None)
    wrapped = pub.encrypt(data_key, _OAEP)
    return {"v": 1, "alg": "RSA-OAEP-256+AES-256-GCM",
            "wrapped_key": _b64(wrapped), "nonce": _b64(nonce), "ct": _b64(ct)}


def unseal(blob: dict, private_pem: str) -> bytes:
    """Descifra un sobre con la KEK privada. Devuelve el plaintext en bytes."""
    priv = serialization.load_pem_private_key(private_pem.encode("ascii"), password=None)
    data_key = priv.decrypt(_ub64(blob["wrapped_key"]), _OAEP)
    return AESGCM(data_key).decrypt(_ub64(blob["nonce"]), _ub64(blob["ct"]), None)


# --- Conveniencia para credenciales {api_key, api_secret} ----------------
def seal_credentials(api_key: str, api_secret: str, public_pem: str) -> dict:
    payload = json.dumps({"api_key": api_key, "api_secret": api_secret}).encode("utf-8")
    return seal(payload, public_pem)


def unseal_credentials(blob: dict, private_pem: str) -> Tuple[str, str]:
    data = json.loads(unseal(blob, private_pem).decode("utf-8"))
    return data["api_key"], data["api_secret"]


# --- Carga de claves desde el entorno ------------------------------------
def public_pem() -> Optional[str]:
    """Clave pública de la KEK (Railway). None si la bóveda no está configurada."""
    pem = os.environ.get("NEXUX_KEK_PUBLIC", "").strip()
    return pem or None


def private_pem() -> Optional[str]:
    """Clave privada de la KEK (VPS): env o ~/.nexus/kek_private.pem. None si no hay."""
    pem = os.environ.get("NEXUX_KEK_PRIVATE", "").strip()
    if pem:
        return pem
    path = os.path.expanduser("~/.nexus/kek_private.pem")
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    return None


def vault_ready() -> bool:
    """True si la web puede cifrar (hay clave pública configurada)."""
    return public_pem() is not None


if __name__ == "__main__":
    # `python -m core.vault generate` → imprime el par de llaves para el setup.
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "generate":
        priv, pub = generate_keypair()
        print("=== NEXUX_KEK_PRIVATE (solo en el VPS: ~/.nexus/kek_private.pem, chmod 600) ===")
        print(priv)
        print("=== NEXUX_KEK_PUBLIC (variable de entorno en Railway) ===")
        print(pub)
    else:
        print("uso: python -m core.vault generate")
