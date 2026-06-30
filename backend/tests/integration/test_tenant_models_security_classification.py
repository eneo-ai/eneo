"""Integration tests for tenant model routers focused on security classification.

Covers the three create/update endpoints under `/api/v1/admin/tenant-models/`:
- POST /api/v1/admin/tenant-models/{completion,embedding,transcription}/
- PUT  /api/v1/admin/tenant-models/{completion,embedding,transcription}/{id}/

These tests exercise the cross-cutting behaviour added when the wizard learned
to send `security_classification` directly at create time, plus the
`model_fields_set`-based update logic that lets clients clear nullable fields
by sending an explicit `null`. The cross-tenant guard is the highest-risk
piece — the helper in
`eneo.security_classifications.tenant_validation` is the single point of
enforcement for all three routers, so we verify it from each.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.ai_models_table import (
    CompletionModels,
    EmbeddingModels,
    TranscriptionModels,
)
from eneo.database.tables.security_classifications_table import SecurityClassification
from eneo.database.tables.tenant_table import Tenants

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def default_user(db_container):
    async with db_container() as container:
        user_repo = container.user_repo()
        return await user_repo.get_user_by_email("test@example.com")


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, default_user):
    async with db_container() as container:
        auth_service = container.auth_service()
        return auth_service.create_access_token_for_user(default_user)


@pytest.fixture
async def tenant_provider_id(db_container, default_user):
    """The seeded OpenAI provider for the default tenant.

    `seed_default_models` (autouse) creates exactly one provider per tenant.
    """
    from eneo.database.tables.model_providers_table import ModelProviders

    async with db_container() as container:
        session = container.session()
        result = await session.execute(
            sa.select(ModelProviders.id).where(
                ModelProviders.tenant_id == default_user.tenant_id
            )
        )
        return str(result.scalar_one())


@pytest.fixture
async def tenant_classification(db_container, default_user):
    async with db_container() as container:
        session = container.session()
        classification = SecurityClassification(
            name=f"internal-{uuid4().hex[:8]}",
            description="internal use only",
            security_level=10,
            tenant_id=default_user.tenant_id,
        )
        session.add(classification)
        await session.flush()
        return classification.id


@pytest.fixture
async def other_tenant_classification(db_container):
    """A classification belonging to a *different* tenant.

    Used to make sure cross-tenant ID's are rejected as "not found" — never
    accepted as if they belonged to the caller.
    """
    async with db_container() as container:
        session = container.session()
        other_tenant = Tenants(
            name=f"other-tenant-{uuid4().hex[:8]}",
            quota_limit=1_000_000,
            state="active",
        )
        session.add(other_tenant)
        await session.flush()

        classification = SecurityClassification(
            name="cross-tenant-secret",
            description="not for the default tenant",
            security_level=99,
            tenant_id=other_tenant.id,
        )
        session.add(classification)
        await session.flush()
        return classification.id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _completion_payload(provider_id: str, **overrides) -> dict:
    body = {
        "provider_id": provider_id,
        "name": f"completion-{uuid4().hex[:8]}",
        "display_name": f"Test completion {uuid4().hex[:8]}",
        "max_input_tokens": 8000,
        "max_output_tokens": 4096,
    }
    body.update(overrides)
    return body


def _embedding_payload(provider_id: str, **overrides) -> dict:
    body = {
        "provider_id": provider_id,
        "name": f"embedding-{uuid4().hex[:8]}",
        "display_name": f"Test embedding {uuid4().hex[:8]}",
    }
    body.update(overrides)
    return body


def _transcription_payload(provider_id: str, **overrides) -> dict:
    body = {
        "provider_id": provider_id,
        "name": f"transcription-{uuid4().hex[:8]}",
        "display_name": f"Test transcription {uuid4().hex[:8]}",
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# Completion: create
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_completion_with_valid_classification(
    client,
    admin_token,
    tenant_provider_id,
    tenant_classification,
    db_container,
):
    response = await client.post(
        "/api/v1/admin/tenant-models/completion/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json=_completion_payload(
            tenant_provider_id,
            security_classification={"id": str(tenant_classification)},
        ),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["security_classification"] is not None
    assert body["security_classification"]["id"] == str(tenant_classification)

    async with db_container() as container:
        session = container.session()
        stored = await session.execute(
            sa.select(CompletionModels.security_classification_id).where(
                CompletionModels.id == body["id"]
            )
        )
        assert stored.scalar_one() == tenant_classification


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_completion_without_classification(
    client,
    admin_token,
    tenant_provider_id,
):
    response = await client.post(
        "/api/v1/admin/tenant-models/completion/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json=_completion_payload(tenant_provider_id),
    )
    assert response.status_code == 200, response.text
    assert response.json()["security_classification"] is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_completion_description_is_stored_verbatim(
    client,
    admin_token,
    tenant_provider_id,
    db_container,
):
    """Whatever the admin sends in `description` is what we store — no
    placeholder fallback. Regression guard for the old completion-router
    behaviour that auto-filled `Tenant model: <display_name>` and silently
    overrode an empty submission."""
    no_description = await client.post(
        "/api/v1/admin/tenant-models/completion/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json=_completion_payload(tenant_provider_id),
    )
    assert no_description.status_code == 200, no_description.text

    explicit = await client.post(
        "/api/v1/admin/tenant-models/completion/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json=_completion_payload(tenant_provider_id, description="my notes"),
    )
    assert explicit.status_code == 200, explicit.text

    async with db_container() as container:
        session = container.session()
        no_desc_row = (
            await session.execute(
                sa.select(CompletionModels.description).where(
                    CompletionModels.id == no_description.json()["id"]
                )
            )
        ).scalar_one()
        explicit_row = (
            await session.execute(
                sa.select(CompletionModels.description).where(
                    CompletionModels.id == explicit.json()["id"]
                )
            )
        ).scalar_one()

    assert no_desc_row is None
    assert explicit_row == "my notes"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_completion_with_unknown_classification_404(
    client,
    admin_token,
    tenant_provider_id,
):
    response = await client.post(
        "/api/v1/admin/tenant-models/completion/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json=_completion_payload(
            tenant_provider_id,
            security_classification={"id": str(uuid4())},
        ),
    )
    assert response.status_code == 404, response.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_completion_rejects_cross_tenant_classification(
    client,
    admin_token,
    tenant_provider_id,
    other_tenant_classification,
):
    """Cross-tenant ID's must be rejected — leaking another tenant's
    classification onto our model would silently broaden the model's
    availability under tenants where security classifications gate which
    models a space sees."""
    response = await client.post(
        "/api/v1/admin/tenant-models/completion/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json=_completion_payload(
            tenant_provider_id,
            security_classification={"id": str(other_tenant_classification)},
        ),
    )
    assert response.status_code == 404, response.text


# ---------------------------------------------------------------------------
# Completion: update — model_fields_set semantics
# ---------------------------------------------------------------------------


async def _create_completion_model(client, admin_token, provider_id, **overrides):
    response = await client.post(
        "/api/v1/admin/tenant-models/completion/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json=_completion_payload(provider_id, **overrides),
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_completion_can_clear_nullable_fields(
    client,
    admin_token,
    tenant_provider_id,
    db_container,
):
    """Nullable fields (description, input/output cost) must be clearable by
    sending an explicit `null`. This is the behaviour change introduced when
    the routers switched to `model_fields_set`."""
    created = await _create_completion_model(
        client,
        admin_token,
        tenant_provider_id,
        description="initial",
        input_cost_per_token=0.0001,
        output_cost_per_token=0.0002,
    )
    model_id = created["id"]

    response = await client.put(
        f"/api/v1/admin/tenant-models/completion/{model_id}/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "description": None,
            "input_cost_per_token": None,
            "output_cost_per_token": None,
        },
    )
    assert response.status_code == 200, response.text

    async with db_container() as container:
        session = container.session()
        row = (
            await session.execute(
                sa.select(
                    CompletionModels.description,
                    CompletionModels.input_cost_per_token,
                    CompletionModels.output_cost_per_token,
                ).where(CompletionModels.id == model_id)
            )
        ).one()
        assert row.description is None
        assert row.input_cost_per_token is None
        assert row.output_cost_per_token is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_completion_omitted_field_preserved(
    client,
    admin_token,
    tenant_provider_id,
    db_container,
):
    """Fields *not* present in the body must stay unchanged. Regression guard
    for any future refactor that goes back to "is not None" — that pattern
    cannot tell "field omitted" from "field set to null"."""
    created = await _create_completion_model(
        client,
        admin_token,
        tenant_provider_id,
        description="keep me",
        input_cost_per_token=0.0005,
    )
    model_id = created["id"]

    response = await client.put(
        f"/api/v1/admin/tenant-models/completion/{model_id}/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"display_name": "renamed"},
    )
    assert response.status_code == 200, response.text

    async with db_container() as container:
        session = container.session()
        row = (
            await session.execute(
                sa.select(
                    CompletionModels.nickname,
                    CompletionModels.description,
                    CompletionModels.input_cost_per_token,
                ).where(CompletionModels.id == model_id)
            )
        ).one()
        assert row.nickname == "renamed"
        assert row.description == "keep me"
        assert row.input_cost_per_token == Decimal("0.000500000000")


# ---------------------------------------------------------------------------
# Embedding: smoke tests for the same cross-tenant guard
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_embedding_with_valid_classification(
    client,
    admin_token,
    tenant_provider_id,
    tenant_classification,
    db_container,
):
    response = await client.post(
        "/api/v1/admin/tenant-models/embedding/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json=_embedding_payload(
            tenant_provider_id,
            security_classification={"id": str(tenant_classification)},
        ),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["security_classification"] is not None
    assert body["security_classification"]["id"] == str(tenant_classification)

    async with db_container() as container:
        session = container.session()
        stored = await session.execute(
            sa.select(EmbeddingModels.security_classification_id).where(
                EmbeddingModels.id == body["id"]
            )
        )
        assert stored.scalar_one() == tenant_classification


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_embedding_rejects_cross_tenant_classification(
    client,
    admin_token,
    tenant_provider_id,
    other_tenant_classification,
):
    response = await client.post(
        "/api/v1/admin/tenant-models/embedding/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json=_embedding_payload(
            tenant_provider_id,
            security_classification={"id": str(other_tenant_classification)},
        ),
    )
    assert response.status_code == 404, response.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_embedding_can_clear_dimensions_and_cost(
    client,
    admin_token,
    tenant_provider_id,
    db_container,
):
    create_response = await client.post(
        "/api/v1/admin/tenant-models/embedding/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json=_embedding_payload(
            tenant_provider_id,
            dimensions=1536,
            max_input=8191,
            input_cost_per_token=0.00001,
        ),
    )
    assert create_response.status_code == 200, create_response.text
    model_id = create_response.json()["id"]

    response = await client.put(
        f"/api/v1/admin/tenant-models/embedding/{model_id}/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "dimensions": None,
            "max_input": None,
            "input_cost_per_token": None,
        },
    )
    assert response.status_code == 200, response.text

    async with db_container() as container:
        session = container.session()
        row = (
            await session.execute(
                sa.select(
                    EmbeddingModels.dimensions,
                    EmbeddingModels.max_input,
                    EmbeddingModels.input_cost_per_token,
                ).where(EmbeddingModels.id == model_id)
            )
        ).one()
        assert row.dimensions is None
        assert row.max_input is None
        assert row.input_cost_per_token is None


# ---------------------------------------------------------------------------
# Transcription: smoke tests for the same cross-tenant guard
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_transcription_with_valid_classification(
    client,
    admin_token,
    tenant_provider_id,
    tenant_classification,
    db_container,
):
    response = await client.post(
        "/api/v1/admin/tenant-models/transcription/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json=_transcription_payload(
            tenant_provider_id,
            security_classification={"id": str(tenant_classification)},
        ),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["security_classification"] is not None
    assert body["security_classification"]["id"] == str(tenant_classification)

    async with db_container() as container:
        session = container.session()
        stored = await session.execute(
            sa.select(TranscriptionModels.security_classification_id).where(
                TranscriptionModels.id == body["id"]
            )
        )
        assert stored.scalar_one() == tenant_classification


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_transcription_rejects_cross_tenant_classification(
    client,
    admin_token,
    tenant_provider_id,
    other_tenant_classification,
):
    response = await client.post(
        "/api/v1/admin/tenant-models/transcription/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json=_transcription_payload(
            tenant_provider_id,
            security_classification={"id": str(other_tenant_classification)},
        ),
    )
    assert response.status_code == 404, response.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_transcription_can_clear_cost_per_minute(
    client,
    admin_token,
    tenant_provider_id,
    db_container,
):
    create_response = await client.post(
        "/api/v1/admin/tenant-models/transcription/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json=_transcription_payload(tenant_provider_id, cost_per_minute=0.012),
    )
    assert create_response.status_code == 200, create_response.text
    model_id = create_response.json()["id"]

    response = await client.put(
        f"/api/v1/admin/tenant-models/transcription/{model_id}/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"cost_per_minute": None},
    )
    assert response.status_code == 200, response.text

    async with db_container() as container:
        session = container.session()
        stored = await session.execute(
            sa.select(TranscriptionModels.cost_per_minute).where(
                TranscriptionModels.id == model_id
            )
        )
        assert stored.scalar_one() is None


# ---------------------------------------------------------------------------
# Security classification deletion guard
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_classification_blocked_when_referenced_by_model(
    client,
    admin_token,
    tenant_provider_id,
    tenant_classification,
):
    """Deleting a classification that's still referenced by a tenant model
    must be refused (default behaviour). Otherwise the FK's `ON DELETE
    SET NULL` would silently strip the classification from every model
    that had it, opening them up to spaces that previously couldn't see
    them."""
    create = await client.post(
        "/api/v1/admin/tenant-models/completion/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json=_completion_payload(
            tenant_provider_id,
            security_classification={"id": str(tenant_classification)},
        ),
    )
    assert create.status_code == 200, create.text

    delete = await client.delete(
        f"/api/v1/security-classifications/{tenant_classification}/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert delete.status_code == 400, delete.text
    assert "in use" in delete.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_classification_allowed_with_force_flag(
    client,
    admin_token,
    tenant_provider_id,
    tenant_classification,
    db_container,
):
    """`?force=true` is the explicit opt-in for the loosen-everything
    behaviour. We verify the dependent model survives but loses its
    classification, matching the FK's `ON DELETE SET NULL`."""
    create = await client.post(
        "/api/v1/admin/tenant-models/completion/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json=_completion_payload(
            tenant_provider_id,
            security_classification={"id": str(tenant_classification)},
        ),
    )
    assert create.status_code == 200, create.text
    model_id = create.json()["id"]

    delete = await client.delete(
        f"/api/v1/security-classifications/{tenant_classification}/?force=true",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert delete.status_code == 204, delete.text

    async with db_container() as container:
        session = container.session()
        stored = await session.execute(
            sa.select(CompletionModels.security_classification_id).where(
                CompletionModels.id == model_id
            )
        )
        assert stored.scalar_one() is None


# ---------------------------------------------------------------------------
# Tenant isolation on update
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_completion_in_other_tenant_404(
    client,
    admin_token,
    db_container,
    default_user,
):
    """A model belonging to another tenant must not be reachable through this
    tenant's update endpoint, even with a valid admin token."""
    from eneo.database.tables.model_providers_table import ModelProviders

    async with db_container() as container:
        session = container.session()
        other_tenant = Tenants(
            name=f"other-{uuid4().hex[:8]}",
            quota_limit=1_000_000,
            state="active",
        )
        session.add(other_tenant)
        await session.flush()

        # A user is required to load the seeded provider for the new tenant
        # via the seed_default_models patch. We bypass that here by creating
        # the provider + model directly.
        provider = ModelProviders(
            tenant_id=other_tenant.id,
            name="OpenAI",
            provider_type="openai",
            credentials={"api_key": "x"},
            config={},
            is_active=True,
        )
        session.add(provider)
        await session.flush()

        foreign_model = CompletionModels(
            tenant_id=other_tenant.id,
            provider_id=provider.id,
            name="other-tenant-model",
            nickname="Other tenant model",
            family="openai",
            max_input_tokens=8000,
            max_output_tokens=4096,
            is_deprecated=False,
            stability="stable",
            hosting="usa",
            open_source=False,
            org="OpenAI",
            vision=False,
            reasoning=False,
            base_url="https://api.openai.com/v1",
            litellm_model_name="gpt-4",
            is_enabled=True,
            is_default=False,
        )
        session.add(foreign_model)
        await session.flush()
        foreign_model_id = foreign_model.id

    response = await client.put(
        f"/api/v1/admin/tenant-models/completion/{foreign_model_id}/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"display_name": "hijacked"},
    )
    assert response.status_code == 404, response.text


# ---------------------------------------------------------------------------
# Update: is_default + security_classification (the legacy edit-dialog path
# used to split these across a second /models/{id} PUT, which could partial-
# fail and leave the UI showing fields that disagreed with the DB. Folding
# them into the tenant update endpoint means one transaction, one audit.)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_completion_promotes_default_and_unsets_sibling(
    client,
    admin_token,
    tenant_provider_id,
    db_container,
):
    """is_default=True must demote any existing default in the same tenant.

    The schema accepts multiple defaults; the UI assumes at most one. The
    create path already unsets siblings — update must match so flipping the
    default through the edit dialog doesn't leave two defaults active."""
    first = await _create_completion_model(
        client, admin_token, tenant_provider_id, is_default=True
    )
    second = await _create_completion_model(
        client, admin_token, tenant_provider_id, is_default=False
    )

    response = await client.put(
        f"/api/v1/admin/tenant-models/completion/{second['id']}/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"is_default": True},
    )
    assert response.status_code == 200, response.text

    async with db_container() as container:
        session = container.session()
        rows = (
            await session.execute(
                sa.select(CompletionModels.id, CompletionModels.is_default).where(
                    CompletionModels.id.in_([first["id"], second["id"]])
                )
            )
        ).all()
    defaults = {str(r.id): r.is_default for r in rows}
    assert defaults[second["id"]] is True
    assert defaults[first["id"]] is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_completion_sets_and_clears_security_classification(
    client,
    admin_token,
    tenant_provider_id,
    tenant_classification,
    db_container,
):
    """Round-trip: set classification through update, then clear it.

    `security_classification` is a `ModelId | None`; sending `null`
    explicitly must clear it (legacy two-step save used to need a separate
    request for this)."""
    created = await _create_completion_model(client, admin_token, tenant_provider_id)
    model_id = created["id"]

    set_response = await client.put(
        f"/api/v1/admin/tenant-models/completion/{model_id}/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"security_classification": {"id": str(tenant_classification)}},
    )
    assert set_response.status_code == 200, set_response.text
    assert set_response.json()["security_classification"]["id"] == str(
        tenant_classification
    )

    clear_response = await client.put(
        f"/api/v1/admin/tenant-models/completion/{model_id}/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"security_classification": None},
    )
    assert clear_response.status_code == 200, clear_response.text
    assert clear_response.json()["security_classification"] is None

    async with db_container() as container:
        session = container.session()
        stored = await session.execute(
            sa.select(CompletionModels.security_classification_id).where(
                CompletionModels.id == model_id
            )
        )
        assert stored.scalar_one() is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_completion_rejects_cross_tenant_classification(
    client,
    admin_token,
    tenant_provider_id,
    other_tenant_classification,
):
    """Same cross-tenant guard as create — the legacy save path used to bypass
    this entirely because the second request went through a different
    endpoint that didn't share the tenant_validation helper."""
    created = await _create_completion_model(client, admin_token, tenant_provider_id)

    response = await client.put(
        f"/api/v1/admin/tenant-models/completion/{created['id']}/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"security_classification": {"id": str(other_tenant_classification)}},
    )
    assert response.status_code == 404, response.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_completion_combines_default_and_classification(
    client,
    admin_token,
    tenant_provider_id,
    tenant_classification,
    db_container,
):
    """A single PUT mutating both fields succeeds atomically. Regression guard
    for the partial-success case the legacy two-step save was prone to."""
    created = await _create_completion_model(client, admin_token, tenant_provider_id)
    model_id = created["id"]

    response = await client.put(
        f"/api/v1/admin/tenant-models/completion/{model_id}/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "display_name": "promoted",
            "is_default": True,
            "security_classification": {"id": str(tenant_classification)},
        },
    )
    assert response.status_code == 200, response.text

    async with db_container() as container:
        session = container.session()
        row = (
            await session.execute(
                sa.select(
                    CompletionModels.nickname,
                    CompletionModels.is_default,
                    CompletionModels.security_classification_id,
                ).where(CompletionModels.id == model_id)
            )
        ).one()
    assert row.nickname == "promoted"
    assert row.is_default is True
    assert row.security_classification_id == tenant_classification


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_embedding_promotes_default_and_clears_classification(
    client,
    admin_token,
    tenant_provider_id,
    tenant_classification,
    db_container,
):
    """Embedding mirror of the completion update test — same contract, same
    service helpers, but the three model types each have their own table so
    the unset-siblings path is exercised independently."""
    created = await client.post(
        "/api/v1/admin/tenant-models/embedding/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json=_embedding_payload(
            tenant_provider_id,
            is_default=False,
            security_classification={"id": str(tenant_classification)},
        ),
    )
    assert created.status_code == 200, created.text
    model_id = created.json()["id"]

    response = await client.put(
        f"/api/v1/admin/tenant-models/embedding/{model_id}/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"is_default": True, "security_classification": None},
    )
    assert response.status_code == 200, response.text

    async with db_container() as container:
        session = container.session()
        row = (
            await session.execute(
                sa.select(
                    EmbeddingModels.is_default,
                    EmbeddingModels.security_classification_id,
                ).where(EmbeddingModels.id == model_id)
            )
        ).one()
    assert row.is_default is True
    assert row.security_classification_id is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_transcription_promotes_default_and_sets_classification(
    client,
    admin_token,
    tenant_provider_id,
    tenant_classification,
    db_container,
):
    """Transcription mirror — completes coverage across all three tenant
    model types so a future refactor of the shared helpers can't regress one
    silently."""
    created = await client.post(
        "/api/v1/admin/tenant-models/transcription/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json=_transcription_payload(tenant_provider_id, is_default=False),
    )
    assert created.status_code == 200, created.text
    model_id = created.json()["id"]

    response = await client.put(
        f"/api/v1/admin/tenant-models/transcription/{model_id}/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "is_default": True,
            "security_classification": {"id": str(tenant_classification)},
        },
    )
    assert response.status_code == 200, response.text

    async with db_container() as container:
        session = container.session()
        row = (
            await session.execute(
                sa.select(
                    TranscriptionModels.is_default,
                    TranscriptionModels.security_classification_id,
                ).where(TranscriptionModels.id == model_id)
            )
        ).one()
    assert row.is_default is True
    assert row.security_classification_id == tenant_classification
