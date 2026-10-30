"""Seed the E2E tenant with models wired to the mock server.

Runs at stack startup (after init_db). Creates a model provider whose
`endpoint` points at the in-network mock, and on it a default completion model
a default embedding model and a default transcription model: the personal chat
resolves a working, deterministic model, and a new space starts with the
embedding model its knowledge collections need and the transcription model an
app needs to be created, as with a real organisation's defaults. Idempotent:
each row is created only when missing, so a rerun also completes a database
seeded by an older version of this script.

The provider's API key is stored encrypted with the stack's fixed test
ENCRYPTION_KEY, as the backend stores keys in production: with a key set it
refuses plaintext credentials. A key left in plaintext by an older version of
this script is encrypted on the next run. Without ENCRYPTION_KEY (an older
compose file) the key stays plaintext, which the backend then reads as-is.
"""

import asyncio
import os
from uuid import UUID

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.database import sessionmanager
from eneo.database.tables.ai_models_table import (
    CompletionModels,
    EmbeddingModels,
    TranscriptionModels,
)
from eneo.database.tables.model_providers_table import ModelProviders
from eneo.database.tables.roles_table import Roles
from eneo.database.tables.tenant_table import Tenants
from eneo.main.config import get_settings
from eneo.server.dependencies.predefined_roles import (
    load_predefined_roles_from_config,
)
from eneo.settings.encryption_service import EncryptionService

MOCK_ENDPOINT = "http://e2e-mock-model:8200/v1"
TENANT_NAME = os.environ.get("E2E_TENANT_NAME", "E2ETenant")
# A default transcription model also permits app creation in the E2E space.
TRANSCRIPTION_MODEL_NAME = os.environ.get("E2E_TRANSCRIPTION_MODEL", "e2e-mock-transcription")
PROVIDER_NAME = "E2E Mock Provider"
# A dummy: the mock accepts any key.
API_KEY = "test-key"
MODEL_NAME = "e2e-mock"
EMBEDDING_MODEL_NAME = "e2e-mock-embedding"
OWNER_ROLE_SOURCE = "Owner"
PERMISSIONS_ADAPTER = TypeAdapter(list[str])


def _predefined_owner_permissions() -> list[str]:
    for template in load_predefined_roles_from_config():
        name: object = template.get("name")
        if name != OWNER_ROLE_SOURCE:
            continue
        raw_permissions: object = template.get("permissions")
        try:
            return PERMISSIONS_ADAPTER.validate_python(raw_permissions, strict=True)
        except ValidationError as exc:
            raise RuntimeError(
                "Predefined Owner role permissions must be strings."
            ) from exc

    raise RuntimeError("Predefined Owner role template not found.")


async def _ensure_owner_permissions(session: AsyncSession, tenant_id: UUID) -> None:
    role = (
        await session.execute(
            select(Roles).where(
                Roles.tenant_id == tenant_id,
                Roles.predefined_source == OWNER_ROLE_SOURCE,
            )
        )
    ).scalar_one_or_none()
    if role is None:
        role = (
            await session.execute(
                select(Roles).where(
                    Roles.tenant_id == tenant_id,
                    Roles.name == OWNER_ROLE_SOURCE,
                )
            )
        ).scalar_one_or_none()
    if role is None:
        raise RuntimeError("E2E Owner role not found.")

    template_permissions = _predefined_owner_permissions()
    existing_permissions = list(role.permissions)
    missing_permissions = [
        permission
        for permission in template_permissions
        if permission not in existing_permissions
    ]
    if not missing_permissions:
        return

    # init_db creates Owner before granular Flow permissions; boot seeding skips
    # sourced roles, so E2E merges from the predefined-role source of truth.
    role.permissions = [*existing_permissions, *missing_permissions]
    print(
        "[seed] merged E2E Owner permissions from predefined role template",
        flush=True,
    )


async def main() -> None:
    done: list[str] = []
    settings = get_settings()
    encryption = EncryptionService(settings)

    def stored_key(api_key: str) -> str:
        return encryption.encrypt(api_key) if encryption.is_active() else api_key

    sessionmanager.init(settings.database_url)
    async with sessionmanager.session() as session, session.begin():
        tenant_id = (
            await session.execute(select(Tenants.id).where(Tenants.name == TENANT_NAME))
        ).scalar_one()

        await _ensure_owner_permissions(session, tenant_id)

        provider = (
            await session.execute(
                select(ModelProviders).where(
                    ModelProviders.tenant_id == tenant_id,
                    ModelProviders.name == PROVIDER_NAME,
                )
            )
        ).scalar_one_or_none()
        if provider is None:
            provider = ModelProviders(
                tenant_id=tenant_id,
                name=PROVIDER_NAME,
                provider_type="openai",
                credentials={
                    "api_key": stored_key(API_KEY),
                    "endpoint": MOCK_ENDPOINT,
                },
                config={"endpoint": MOCK_ENDPOINT},
                is_active=True,
            )
            session.add(provider)
            await session.flush()
            done.append("created E2E mock provider")
        elif encryption.is_active() and not encryption.is_encrypted(
            provider.credentials.get("api_key", "")
        ):
            # Seeded in plaintext before the stack had a key: unreadable now.
            provider.credentials = {
                **provider.credentials,
                "api_key": stored_key(API_KEY),
            }
            done.append("encrypted the E2E mock provider's key")
        provider_id = provider.id

        async def add_if_missing(
            model: CompletionModels | EmbeddingModels | TranscriptionModels, kind: str
        ):
            table = type(model)
            existing = await session.execute(
                select(table.id).where(
                    table.provider_id == provider_id, table.name == model.name
                )
            )
            if existing.scalar_one_or_none() is None:
                session.add(model)
                done.append(f"created {kind} {model.name}")

        await add_if_missing(
            CompletionModels(
                name=MODEL_NAME,
                nickname="E2E Mock",
                max_input_tokens=32768,
                max_output_tokens=2048,
                family="openai",
                stability="stable",
                hosting="usa",
                org="OpenAI",
                vision=False,
                reasoning=False,
                supports_tool_calling=True,
                base_url=MOCK_ENDPOINT,
                litellm_model_name=MODEL_NAME,
                tenant_id=tenant_id,
                provider_id=provider_id,
                is_enabled=True,
                is_default=True,
            ),
            "default completion model",
        )
        # Enabled like an admin-added organisation model, so every new space
        # gets it (a space starts with the newest usable embedding model).
        await add_if_missing(
            EmbeddingModels(
                name=EMBEDDING_MODEL_NAME,
                nickname="E2E Mock Embedding",
                open_source=False,
                # Left unset: LiteLLM refuses `dimensions` on an "openai"
                # provider unless the model is a text-embedding-3, so the
                # mock's vectors have a fixed size instead.
                dimensions=None,
                max_input=8191,
                family="openai",
                stability="stable",
                hosting="usa",
                org="OpenAI",
                tenant_id=tenant_id,
                provider_id=provider_id,
                is_enabled=True,
                is_default=True,
            ),
            "default embedding model",
        )
        if TRANSCRIPTION_MODEL_NAME:
            await add_if_missing(
                TranscriptionModels(
                    name=TRANSCRIPTION_MODEL_NAME,
                    model_name=TRANSCRIPTION_MODEL_NAME,
                    nickname="E2E Mock Transcription",
                    open_source=False,
                    family="openai",
                    stability="stable",
                    hosting="usa",
                    org="OpenAI",
                    base_url=MOCK_ENDPOINT,
                    tenant_id=tenant_id,
                    provider_id=provider_id,
                    is_enabled=True,
                    is_default=True,
                ),
                "default transcription model",
            )

    for item in done:
        print(f"[seed] {item}", flush=True)
    if not done:
        print(
            "[seed] E2E mock provider and models already present, skipping",
            flush=True,
        )


if __name__ == "__main__":
    asyncio.run(main())
