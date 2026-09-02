"""Application-level encryption for secrets at rest (docs/03 §Szyfrowanie tokenów).

Master key: TOKEN_MASTER_KEY (32 B, base64) from the environment — never in the DB.
Per-scope key: HKDF-SHA256(master, info=scope), e.g. "tenant:<uuid>" or "user:<uuid>".
Cipher: AES-256-GCM, random 12 B nonce. Blob format (bytes): b"v1|" + nonce + ciphertext+tag.
The version prefix allows key rotation (`manage.py rotate_token_key`, stage 6).
"""

import base64
import os
from functools import lru_cache

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings

_VERSION = b"v1"
_NONCE_LEN = 12


class CryptoError(Exception):
    pass


@lru_cache(maxsize=1)
def _master_key() -> bytes:
    raw = settings.TOKEN_MASTER_KEY
    if not raw:
        raise CryptoError("TOKEN_MASTER_KEY is not set (deploy/.env)")
    try:
        key = base64.b64decode(raw, validate=True)
    except ValueError as exc:
        raise CryptoError("TOKEN_MASTER_KEY must be base64") from exc
    if len(key) != 32:
        raise CryptoError("TOKEN_MASTER_KEY must decode to exactly 32 bytes")
    return key


def _scope_key(scope: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=scope.encode()).derive(
        _master_key()
    )


def encrypt(scope: str, plaintext: bytes) -> bytes:
    nonce = os.urandom(_NONCE_LEN)
    sealed = AESGCM(_scope_key(scope)).encrypt(nonce, plaintext, scope.encode())
    return _VERSION + b"|" + nonce + sealed


def decrypt(scope: str, blob: bytes) -> bytes:
    version, sep, rest = bytes(blob).partition(b"|")
    if not sep or version != _VERSION:
        raise CryptoError(f"unsupported blob version {version!r}")
    nonce, sealed = rest[:_NONCE_LEN], rest[_NONCE_LEN:]
    try:
        return AESGCM(_scope_key(scope)).decrypt(nonce, sealed, scope.encode())
    except Exception as exc:  # InvalidTag and friends — never leak which
        raise CryptoError("decryption failed") from exc
