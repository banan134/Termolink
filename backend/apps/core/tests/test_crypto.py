import pytest
from django.test import override_settings

from apps.core import crypto


def test_roundtrip_and_scope_binding() -> None:
    blob = crypto.encrypt("user:1", b"secret")
    assert blob.startswith(b"v1|")
    assert crypto.decrypt("user:1", blob) == b"secret"
    with pytest.raises(crypto.CryptoError):
        crypto.decrypt("user:2", blob)


def test_tamper_and_bad_version() -> None:
    blob = bytearray(crypto.encrypt("t", b"x"))
    blob[-1] ^= 1
    with pytest.raises(crypto.CryptoError):
        crypto.decrypt("t", bytes(blob))
    with pytest.raises(crypto.CryptoError):
        crypto.decrypt("t", b"v0|" + b"\x00" * 20)


def test_missing_master_key_is_a_clear_error() -> None:
    crypto._master_key.cache_clear()
    try:
        with override_settings(TOKEN_MASTER_KEY=""), pytest.raises(crypto.CryptoError):
            crypto.encrypt("t", b"x")
    finally:
        crypto._master_key.cache_clear()
