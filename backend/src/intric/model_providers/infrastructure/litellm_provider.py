from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

import sqlalchemy as sa

from intric.database.tables.model_providers_table import ModelProviders
from intric.main.exceptions import (
    APIKeyNotConfiguredException,
    ProviderInactiveException,
    ProviderNotFoundException,
)
from intric.model_providers.infrastructure.tenant_model_credential_resolver import (
    TenantModelCredentialResolver,
)
from intric.tenants.provider_field_config import get_field_definitions

if TYPE_CHECKING:
    from intric.database.database import AsyncSession
    from intric.settings.encryption_service import EncryptionService


@dataclass(frozen=True)
class ResolvedLiteLLMProvider:
    id: UUID
    tenant_id: UUID
    name: str
    provider_type: str
    credentials: dict[str, Any]
    config: dict[str, Any]

    def create_credential_resolver(
        self, encryption_service: "EncryptionService"
    ) -> TenantModelCredentialResolver:
        return TenantModelCredentialResolver(
            provider_id=self.id,
            provider_type=self.provider_type,
            credentials=self.credentials,
            config=self.config,
            encryption_service=encryption_service,
        )


def build_litellm_model_name(provider_type: str, model_name: str) -> str:
    """Build the single canonical model route used for all LiteLLM calls."""
    return f"{provider_type}/{model_name}"


def _build_litellm_provider_kwargs(
    credential_resolver: TenantModelCredentialResolver,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    field_definitions = get_field_definitions(credential_resolver.provider_type)

    for definition in field_definitions:
        field = definition["name"]
        required = definition["required"]

        if field == "api_key":
            api_key = credential_resolver.get_api_key(required=required)
            if api_key:
                kwargs["api_key"] = api_key
            continue

        # The deployment is already represented by the model route. Sending it
        # again changes semantics for some OpenAI-compatible endpoints.
        if field == "deployment_name":
            credential_resolver.get_credential_field(
                field=field,
                required=required,
            )
            continue

        value = credential_resolver.get_credential_field(
            field=field,
            required=required,
        )
        if not value:
            continue

        if field == "endpoint":
            kwargs["api_base"] = value
        else:
            kwargs[field] = value

    # Existing provider records may contain these optional LiteLLM settings
    # even though they are not rendered as setup fields.
    for field in ("api_type", "organization"):
        value = credential_resolver.get_credential_field(field=field)
        if value:
            kwargs[field] = value

    return kwargs


def build_litellm_provider_kwargs(
    credential_resolver: TenantModelCredentialResolver,
) -> dict[str, Any]:
    """Resolve provider config without exposing credential/decryption details."""
    try:
        return _build_litellm_provider_kwargs(credential_resolver)
    except ValueError as exc:
        raise APIKeyNotConfiguredException(
            f"Provider '{credential_resolver.provider_type}' has incomplete or "
            "invalid credentials. Please verify the provider configuration."
        ) from exc


async def load_active_litellm_provider(
    *,
    session: "AsyncSession",
    provider_id: UUID,
    tenant_id: UUID,
) -> ResolvedLiteLLMProvider:
    """Load an active provider within the caller's tenant boundary."""
    stmt = sa.select(ModelProviders).where(
        ModelProviders.id == provider_id,
        ModelProviders.tenant_id == tenant_id,
    )
    result = await session.execute(stmt)
    provider_db = result.scalar_one_or_none()

    if provider_db is None:
        raise ProviderNotFoundException(
            f"Model provider '{provider_id}' not found or is not accessible."
        )

    if not provider_db.is_active:
        raise ProviderInactiveException(
            f"The model provider '{provider_db.name}' is currently inactive. "
            "Please contact your administrator to enable the provider."
        )

    return ResolvedLiteLLMProvider(
        id=provider_db.id,
        tenant_id=provider_db.tenant_id,
        name=provider_db.name,
        provider_type=provider_db.provider_type,
        credentials=provider_db.credentials,
        config=provider_db.config,
    )
