import pytest

from apps.adapters.base import ProviderTokens
from apps.core import crypto
from apps.providers import crypto as token_crypto
from apps.providers.models import ProviderAccount
from apps.tenants.models import Tenant


@pytest.mark.django_db
def test_tokens_roundtrip_and_are_bound_to_tenant() -> None:
    a, b = Tenant.objects.create(name="A"), Tenant.objects.create(name="B")
    account = ProviderAccount(tenant=a, provider="viessmann", refresh_token_enc=b"")
    token_crypto.store_tokens(
        account,
        ProviderTokens(
            access_token="at",
            access_expires_at=1_900_000_000.0,
            refresh_token="rt",
            external_user_id="u1",
        ),
    )
    account.save()
    account.refresh_from_db()
    assert b"rt" not in bytes(account.refresh_token_enc) and b"at" not in bytes(
        account.access_token_enc or b""
    )
    loaded = token_crypto.load_tokens(account)
    assert loaded.refresh_token == "rt" and loaded.access_token == "at"
    assert loaded.access_expires_at == 1_900_000_000.0 and loaded.external_user_id == "u1"

    # moving the blob to another tenant must not decrypt (HKDF scope = tenant id)
    stolen = ProviderAccount(
        tenant=b, provider="viessmann", refresh_token_enc=account.refresh_token_enc
    )
    with pytest.raises(crypto.CryptoError):
        token_crypto.load_tokens(stolen)
