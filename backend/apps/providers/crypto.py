"""Provider token encryption per tenant (docs/03 §Szyfrowanie tokenów) on top of core.crypto."""

from datetime import UTC, datetime

from apps.adapters.base import ProviderTokens
from apps.core import crypto

from .models import ProviderAccount


def _scope(account: ProviderAccount) -> str:
    return f"tenant:{account.tenant_id}"


def store_tokens(account: ProviderAccount, tokens: ProviderTokens) -> None:
    """Encrypt and assign tokens on the account (caller saves)."""
    scope = _scope(account)
    account.refresh_token_enc = crypto.encrypt(scope, tokens.refresh_token.encode())
    account.access_token_enc = (
        crypto.encrypt(scope, tokens.access_token.encode()) if tokens.access_token else None
    )
    account.access_expires_at = (
        datetime.fromtimestamp(tokens.access_expires_at, tz=UTC)
        if tokens.access_expires_at
        else None
    )
    if tokens.external_user_id:
        account.external_user_id = tokens.external_user_id


def load_tokens(account: ProviderAccount) -> ProviderTokens:
    scope = _scope(account)
    access = (
        crypto.decrypt(scope, bytes(account.access_token_enc)).decode()
        if account.access_token_enc
        else None
    )
    return ProviderTokens(
        access_token=access,
        access_expires_at=account.access_expires_at.timestamp()
        if account.access_expires_at
        else None,
        refresh_token=crypto.decrypt(scope, bytes(account.refresh_token_enc)).decode(),
        external_user_id=account.external_user_id,
    )


def token_fields() -> list[str]:
    return ["refresh_token_enc", "access_token_enc", "access_expires_at", "external_user_id"]
