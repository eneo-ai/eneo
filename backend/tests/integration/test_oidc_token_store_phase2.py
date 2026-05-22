"""Phase 2 invariants for the same-IdP MCP OAuth: IdP token persistence.

Phase 2 captures the IdP refresh/access token at the federation callback,
encrypts via the existing ``EncryptionService``, and exposes a revoke
path used by the SvelteKit logout flow. The broker (Phase 3) reads these
rows, so the contract this file pins is:

1. ``upsert`` encrypts both tokens at rest. Ciphertext must carry the
   ``enc:fernet:v1:`` prefix; plaintext is never visible after the call
   returns.
2. ``upsert`` is idempotent on ``(user_id, idp_issuer)`` — re-login
   replaces the prior row in place and clears ``revoked_at``.
3. ``upsert`` no-ops when the IdP did not return a refresh_token (some
   IdPs only issue refresh tokens with the ``offline_access`` scope).
4. ``revoke`` zeroes ciphertext + stamps ``revoked_at`` AND emits an
   audit entry. Subsequent ``get_decrypted`` returns ``None``.
5. ``POST /api/v1/auth/oidc/logout`` revokes every row for the caller.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import sqlalchemy as sa

from intric.database.tables.idp_user_tokens_table import IdpUserTokens


@pytest.fixture
async def default_user(db_container):
    async with db_container() as container:
        user_repo = container.user_repo()
        return await user_repo.get_user_by_email("test@example.com")


@pytest.fixture
async def default_user_token(db_container, patch_auth_service_jwt, default_user):
    async with db_container() as container:
        auth_service = container.auth_service()
        return auth_service.create_access_token_for_user(default_user)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_upsert_encrypts_and_persists_refresh_and_access_tokens(
    db_container, default_user
):
    issuer = "https://keycloak.example/realms/eneo"
    refresh = "rt-secret-abcdef"
    access = "at-secret-123456"
    expires = datetime.now(timezone.utc)

    async with db_container() as container:
        store = container.oidc_token_store()
        row_id = await store.upsert(
            user=default_user,
            idp_issuer=issuer,
            idp_subject="user-1",
            refresh_token=refresh,
            access_token=access,
            access_token_expires_at=expires,
            scopes_granted=["openid", "offline_access"],
        )
        assert row_id is not None

        session = container.session()
        row = (
            await session.execute(
                sa.select(IdpUserTokens).where(IdpUserTokens.id == row_id)
            )
        ).scalar_one()

    # Plaintext must not be stored. Both ciphertexts must use the
    # versioned Fernet prefix the existing EncryptionService writes.
    assert row.refresh_token_ciphertext != refresh
    assert row.access_token_ciphertext != access
    assert row.refresh_token_ciphertext.startswith("enc:fernet:v1:")
    assert row.access_token_ciphertext.startswith("enc:fernet:v1:")
    assert row.revoked_at is None
    assert row.scopes_granted == ["openid", "offline_access"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_decrypted_returns_plaintext(db_container, default_user):
    issuer = "https://keycloak.example/realms/eneo"
    refresh = "rt-secret-abcdef"
    access = "at-secret-123456"

    async with db_container() as container:
        store = container.oidc_token_store()
        await store.upsert(
            user=default_user,
            idp_issuer=issuer,
            idp_subject=None,
            refresh_token=refresh,
            access_token=access,
            access_token_expires_at=None,
            scopes_granted=None,
        )
        tokens = await store.get_decrypted(user_id=default_user.id, idp_issuer=issuer)

    assert tokens is not None
    assert tokens.refresh_token == refresh
    assert tokens.access_token == access


@pytest.mark.integration
@pytest.mark.asyncio
async def test_upsert_is_idempotent_on_user_and_issuer(db_container, default_user):
    """Re-login MUST replace the existing row, not insert a second one."""
    issuer = "https://keycloak.example/realms/eneo"

    async with db_container() as container:
        store = container.oidc_token_store()
        first_id = await store.upsert(
            user=default_user,
            idp_issuer=issuer,
            idp_subject=None,
            refresh_token="rt-first",
            access_token=None,
            access_token_expires_at=None,
            scopes_granted=None,
        )
        second_id = await store.upsert(
            user=default_user,
            idp_issuer=issuer,
            idp_subject=None,
            refresh_token="rt-second",
            access_token=None,
            access_token_expires_at=None,
            scopes_granted=None,
        )

        session = container.session()
        rows = (
            (
                await session.execute(
                    sa.select(IdpUserTokens).where(
                        IdpUserTokens.user_id == default_user.id,
                        IdpUserTokens.idp_issuer == issuer,
                    )
                )
            )
            .scalars()
            .all()
        )

    assert first_id == second_id  # PK preserved across upsert
    assert len(rows) == 1
    tokens = await container.oidc_token_store().get_decrypted(
        user_id=default_user.id, idp_issuer=issuer
    )
    assert tokens is not None
    assert tokens.refresh_token == "rt-second"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_upsert_skips_when_refresh_token_missing(db_container, default_user):
    """No refresh_token means the row is useless for the broker — skip."""
    issuer = "https://entra.example/v2.0"

    async with db_container() as container:
        store = container.oidc_token_store()
        result = await store.upsert(
            user=default_user,
            idp_issuer=issuer,
            idp_subject=None,
            refresh_token=None,
            access_token="at-only",
            access_token_expires_at=None,
            scopes_granted=None,
        )
        assert result is None

        session = container.session()
        rows = (
            (
                await session.execute(
                    sa.select(IdpUserTokens).where(
                        IdpUserTokens.user_id == default_user.id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert rows == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_revoke_zeros_ciphertext_and_stamps_revoked_at(
    db_container, default_user
):
    issuer = "https://keycloak.example/realms/eneo"

    async with db_container() as container:
        store = container.oidc_token_store()
        await store.upsert(
            user=default_user,
            idp_issuer=issuer,
            idp_subject=None,
            refresh_token="rt-secret",
            access_token="at-secret",
            access_token_expires_at=datetime.now(timezone.utc),
            scopes_granted=None,
        )

        revoked_count = await store.revoke(user=default_user)
        assert revoked_count == 1

        session = container.session()
        row = (
            await session.execute(
                sa.select(IdpUserTokens).where(IdpUserTokens.user_id == default_user.id)
            )
        ).scalar_one()
        assert row.refresh_token_ciphertext is None
        assert row.access_token_ciphertext is None
        assert row.access_token_expires_at is None
        assert row.revoked_at is not None

        # get_decrypted hides revoked rows
        assert (
            await store.get_decrypted(user_id=default_user.id, idp_issuer=issuer)
        ) is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_logout_endpoint_revokes_all_user_tokens(
    client, db_container, default_user, default_user_token
):
    """``POST /api/v1/auth/oidc/logout`` revokes every active row for the user."""
    issuer_a = "https://keycloak.example/realms/eneo"
    issuer_b = "https://entra.example/v2.0"

    async with db_container() as container:
        store = container.oidc_token_store()
        await store.upsert(
            user=default_user,
            idp_issuer=issuer_a,
            idp_subject=None,
            refresh_token="rt-a",
            access_token=None,
            access_token_expires_at=None,
            scopes_granted=None,
        )
        await store.upsert(
            user=default_user,
            idp_issuer=issuer_b,
            idp_subject=None,
            refresh_token="rt-b",
            access_token=None,
            access_token_expires_at=None,
            scopes_granted=None,
        )

    response = await client.post(
        "/api/v1/auth/oidc/logout",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert response.status_code == 204, response.text

    async with db_container() as container:
        session = container.session()
        rows = (
            (
                await session.execute(
                    sa.select(IdpUserTokens).where(
                        IdpUserTokens.user_id == default_user.id
                    )
                )
            )
            .scalars()
            .all()
        )

    assert len(rows) == 2
    for row in rows:
        assert row.refresh_token_ciphertext is None
        assert row.access_token_ciphertext is None
        assert row.revoked_at is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_logout_endpoint_requires_authentication(client):
    response = await client.post("/api/v1/auth/oidc/logout")
    assert response.status_code in (401, 403), response.text
