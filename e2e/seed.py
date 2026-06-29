"""Seed the E2E tenant with a completion model wired to the mock server.

Runs once at stack startup (after init_db). Creates a model provider whose
`endpoint` points at the in-network mock, plus a default completion model on it,
so the personal chat resolves a working, deterministic model. Idempotent.

Credentials are stored in plaintext on purpose: the E2E stack runs with
ENCRYPTION_KEY unset (TENANT_CREDENTIALS_ENABLED=false), so the credential
resolver reads them as-is — no real keys, no encryption to manage.
"""

import asyncio
from uuid import UUID

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.database import sessionmanager
from intric.database.tables.ai_models_table import CompletionModels
from intric.database.tables.model_providers_table import ModelProviders
from intric.database.tables.roles_table import Roles
from intric.database.tables.tenant_table import Tenants
from intric.main.config import get_settings
from intric.server.dependencies.predefined_roles import (
    load_predefined_roles_from_config,
)

MOCK_ENDPOINT = "http://e2e-mock-model:8200/v1"
TENANT_NAME = "E2ETenant"
PROVIDER_NAME = "E2E Mock Provider"
MODEL_NAME = "e2e-mock"
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
    sessionmanager.init(get_settings().database_url)
    async with sessionmanager.session() as session, session.begin():
        tenant_id = (
            await session.execute(select(Tenants.id).where(Tenants.name == TENANT_NAME))
        ).scalar_one()

        await _ensure_owner_permissions(session, tenant_id)

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

        provider = ModelProviders()
        provider.tenant_id = tenant_id
        provider.name = PROVIDER_NAME
        provider.provider_type = "openai"
        provider.credentials = {"api_key": "test-key", "endpoint": MOCK_ENDPOINT}
        provider.config = {"endpoint": MOCK_ENDPOINT}
        provider.is_active = True
        session.add(provider)
        await session.flush()

        model = CompletionModels()
        model.name = MODEL_NAME
        model.nickname = "E2E Mock"
        model.max_input_tokens = 8192
        model.max_output_tokens = 2048
        model.family = "openai"
        model.stability = "stable"
        model.hosting = "usa"
        model.org = "OpenAI"
        model.vision = False
        model.reasoning = False
        model.supports_tool_calling = False
        model.base_url = MOCK_ENDPOINT
        model.litellm_model_name = MODEL_NAME
        model.tenant_id = tenant_id
        model.provider_id = provider.id
        model.is_enabled = True
        model.is_default = True
        session.add(model)
        print("[seed] created E2E mock provider + default completion model", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
