"""Seed the E2E tenant with mock models and a migrated helper owner.

Runs at stack startup (after init_db). Creates a model provider whose
`endpoint` points at the in-network mock, and on it a default completion model
a default embedding model and a default transcription model: the personal chat
resolves a working, deterministic model, and a new space starts with the
embedding model its knowledge collections need and the transcription model an
app needs to be created, as with a real organisation's defaults. Idempotent:
each row is created only when missing, so a rerun also completes a database
seeded by an older version of this script.

The tenant is created after migrations, so it also needs the inactive system
user that the help-assistant infrastructure migration adds to existing tenants.

The provider's API key is stored encrypted with the stack's fixed test
ENCRYPTION_KEY, as the backend stores keys in production: with a key set it
refuses plaintext credentials. A key left in plaintext by an older version of
this script is encrypted on the next run. Without ENCRYPTION_KEY (an older
compose file) the key stays plaintext, which the backend then reads as-is.
"""

import asyncio

from sqlalchemy import select

from eneo.database.database import sessionmanager
from eneo.database.tables.ai_models_table import (
    CompletionModels,
    EmbeddingModels,
    TranscriptionModels,
)
from eneo.database.tables.model_providers_table import ModelProviders
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.main.config import get_settings
from eneo.settings.encryption_service import EncryptionService

MOCK_ENDPOINT = "http://e2e-mock-model:8200/v1"
TENANT_NAME = "E2ETenant"
PROVIDER_NAME = "E2E Mock Provider"
# A dummy: the mock accepts any key.
API_KEY = "test-key"
MODEL_NAME = "e2e-mock"
EMBEDDING_MODEL_NAME = "e2e-mock-embedding"
TRANSCRIPTION_MODEL_NAME = "e2e-mock-transcription"


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

        # init_db creates this tenant after the infrastructure migration. Give
        # helper route tests the same inactive owner as a migrated tenant.
        system_user = await session.scalar(
            select(Users.id).where(
                Users.tenant_id == tenant_id, Users.is_system_user.is_(True)
            )
        )
        if system_user is None:
            session.add(
                Users(
                    tenant_id=tenant_id,
                    email=f"system+{tenant_id}@eneo.local",
                    username=f"system+{tenant_id}",
                    email_verified=False,
                    password=None,
                    salt=None,
                    is_active=False,
                    state="inactive",
                    is_system_user=True,
                    used_tokens=0,
                )
            )
            done.append("created E2E helper owner")

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
        # The backend refuses to create an app in a space without one. Runs in
        # the e2e stack stay queued (no worker), so the mock never transcribes.
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
