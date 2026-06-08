"""Seed the E2E tenant with a completion model wired to the mock server.

Runs once at stack startup (after init_db). Creates a model provider whose
`endpoint` points at the in-network mock, plus a default completion model on it,
so the personal chat resolves a working, deterministic model. Idempotent.

Credentials are stored in plaintext on purpose: the E2E stack runs with
ENCRYPTION_KEY unset (TENANT_CREDENTIALS_ENABLED=false), so the credential
resolver reads them as-is — no real keys, no encryption to manage.
"""

import asyncio

from sqlalchemy import select

from intric.database.database import sessionmanager
from intric.database.tables.ai_models_table import CompletionModels
from intric.database.tables.model_providers_table import ModelProviders
from intric.database.tables.tenant_table import Tenants
from intric.main.config import get_settings

MOCK_ENDPOINT = "http://e2e-mock-model:8200/v1"
TENANT_NAME = "E2ETenant"
PROVIDER_NAME = "E2E Mock Provider"
MODEL_NAME = "e2e-mock"


async def main() -> None:
    sessionmanager.init(get_settings().database_url)
    async with sessionmanager.session() as session, session.begin():
        tenant_id = (
            await session.execute(select(Tenants.id).where(Tenants.name == TENANT_NAME))
        ).scalar_one()

        already = (
            await session.execute(
                select(ModelProviders.id).where(
                    ModelProviders.tenant_id == tenant_id,
                    ModelProviders.name == PROVIDER_NAME,
                )
            )
        ).scalar_one_or_none()
        if already:
            print("[seed] E2E mock model already present, skipping", flush=True)
            return

        provider = ModelProviders(
            tenant_id=tenant_id,
            name=PROVIDER_NAME,
            provider_type="openai",
            credentials={"api_key": "test-key", "endpoint": MOCK_ENDPOINT},
            config={"endpoint": MOCK_ENDPOINT},
            is_active=True,
        )
        session.add(provider)
        await session.flush()

        session.add(
            CompletionModels(
                name=MODEL_NAME,
                nickname="E2E Mock",
                max_input_tokens=8192,
                max_output_tokens=2048,
                family="openai",
                stability="stable",
                hosting="usa",
                org="OpenAI",
                vision=False,
                reasoning=False,
                supports_tool_calling=False,
                base_url=MOCK_ENDPOINT,
                litellm_model_name=MODEL_NAME,
                tenant_id=tenant_id,
                provider_id=provider.id,
                is_enabled=True,
                is_default=True,
            )
        )
        print("[seed] created E2E mock provider + default completion model", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
