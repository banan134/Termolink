"""TOTP and backup codes (docs/08). Secrets are stored encrypted per user."""

import hashlib
import secrets

import pyotp
from django.conf import settings

from apps.core import crypto

from .models import User

BACKUP_CODES_COUNT = 10
BACKUP_CODE_LEN = 10  # hex chars


def _scope(user: User) -> str:
    return f"user:{user.id}"


def new_secret() -> str:
    return pyotp.random_base32()


def otpauth_url(user: User, secret: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=settings.TOTP_ISSUER)


def verify_code(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code.strip().replace(" ", ""), valid_window=1)


def store_secret(user: User, secret: str) -> None:
    user.totp_secret_enc = crypto.encrypt(_scope(user), secret.encode())


def load_secret(user: User) -> str | None:
    if not user.totp_secret_enc:
        return None
    return crypto.decrypt(_scope(user), bytes(user.totp_secret_enc)).decode()


def hash_backup_code(code: str) -> str:
    return hashlib.sha256(code.strip().lower().encode()).hexdigest()


def new_backup_codes() -> list[str]:
    return [secrets.token_hex(BACKUP_CODE_LEN // 2) for _ in range(BACKUP_CODES_COUNT)]


def verify_user_code(user: User, code: str) -> bool:
    """True if `code` is a valid TOTP or an unused backup code (which is then consumed).

    Caller must persist `user` (backup_codes_hash may change).
    """
    secret = load_secret(user)
    if secret and verify_code(secret, code):
        return True
    hashed = hash_backup_code(code)
    codes = list(user.backup_codes_hash or [])
    if hashed in codes:
        codes.remove(hashed)
        user.backup_codes_hash = codes
        return True
    return False
