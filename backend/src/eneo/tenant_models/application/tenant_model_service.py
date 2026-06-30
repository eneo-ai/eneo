# MIT License

"""Tenant-model orchestration service.

Pulls the create/update/delete business logic out of the three tenant
routers (`/api/v1/admin/tenant-models/{completion,embedding,transcription}/`)
so the routers stay thin and the rules are tested in one place.

Three classes share helpers via composition rather than inheritance
because the create payloads diverge enough (different field sets,
slightly different default-construction) that a single generic class
would be more cryptic than helpful. The shared parts — provider
validation, default-unsetting, classification resolution, audit
logging — live as private helpers on the module.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

import sqlalchemy as sa

from eneo.ai_models.display_name_validation import (
    validate_unique_display_name as _validate_unique_display_name,
)
from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.completion_models.domain.completion_model_repo import (
    CompletionModelRepository,
)
from eneo.completion_models.domain.model_kwargs_capabilities import (
    snapshot_supported_model_kwargs,
)
from eneo.database.tables.ai_models_table import (
    CompletionModels,
    EmbeddingModels,
    TranscriptionModels,
)
from eneo.embedding_models.domain.embedding_model_repo import EmbeddingModelRepository
from eneo.main.exceptions import (
    BadRequestException,
    ModelInUseException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.model_providers.infrastructure.litellm_provider import (
    build_litellm_model_name,
)
from eneo.model_providers.infrastructure.litellm_transport import (
    get_supported_openai_params,
)
from eneo.model_providers.infrastructure.model_provider_repository import (
    ModelProviderRepository,
)
from eneo.security_classifications.tenant_validation import (
    resolve_tenant_security_classification,
)
from eneo.transcription_models.domain.transcription_model_repo import (
    TranscriptionModelRepository,
)

if TYPE_CHECKING:
    from eneo.audit.application.audit_service import AuditService
    from eneo.completion_models.domain.completion_model import CompletionModel
    from eneo.completion_models.presentation.tenant_completion_models_router import (
        TenantCompletionModelCreate,
        TenantCompletionModelUpdate,
    )
    from eneo.database.database import AsyncSession
    from eneo.embedding_models.domain.embedding_model import EmbeddingModel
    from eneo.embedding_models.presentation.tenant_embedding_models_router import (
        TenantEmbeddingModelCreate,
        TenantEmbeddingModelUpdate,
    )
    from eneo.transcription_models.domain.transcription_model import (
        TranscriptionModel,
    )
    from eneo.transcription_models.presentation.tenant_transcription_models_router import (
        TenantTranscriptionModelCreate,
        TenantTranscriptionModelUpdate,
    )
    from eneo.users.user import UserInDB

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _validate_active_provider(
    session: "AsyncSession", provider_id: UUID, tenant_id: UUID
) -> Any:
    """Confirm the provider exists in this tenant and is currently active.

    Raises `NotFoundException` (cross-tenant or unknown ID) or
    `BadRequestException` (provider exists but disabled).
    """
    repo = ModelProviderRepository(session=session, tenant_id=tenant_id)
    provider = await repo.get_by_id(provider_id)
    if not provider.is_active:
        raise BadRequestException("Model provider is not active")
    return provider


async def _unset_other_defaults(
    session: "AsyncSession", table: Any, tenant_id: UUID
) -> None:
    """Clear `is_default` on every row of `table` for this tenant.

    Called before creating or promoting a new default — the schema
    accepts multiple defaults but the UI assumes at most one. Doing the
    update through SQLAlchemy keeps it in the same transaction as the
    subsequent insert so we never publish a transient state with zero
    (or two) defaults.
    """
    stmt = sa.update(table).where(table.tenant_id == tenant_id).values(is_default=False)
    await session.execute(stmt)


def _snapshot_completion_capabilities(
    provider_type: str,
    model_name: str,
    *,
    reasoning: bool,
) -> dict[str, object]:
    model_route = build_litellm_model_name(provider_type, model_name)
    try:
        supported_params = get_supported_openai_params(model_route)
    except Exception:
        logger.warning(
            "Could not discover model parameter capabilities; using conservative defaults",
            extra={"model_route": model_route},
            exc_info=True,
        )
        supported_params = None
    return snapshot_supported_model_kwargs(
        supported_params, reasoning=reasoning
    ).model_dump()


def _ensure_tenant_owned(model: Any) -> None:
    """Block updates/deletes against rows that escaped the tenant_id filter
    (e.g. global models surfaced through a shared table). The router's
    SELECT already filters by tenant_id; this is the belt-and-braces
    guard for the rare case the row's `tenant_id` itself is NULL."""
    if model.tenant_id is None:
        raise UnauthorizedException("Cannot modify global models")


async def _audit(
    audit_service: "AuditService | None",
    *,
    user: "UserInDB",
    action: ActionType,
    entity_type: EntityType,
    target: Any,
    description: str,
    extra: dict[str, Any] | None = None,
    changes: dict[str, Any] | None = None,
) -> None:
    """Log a tenant-model write to the audit log. No-op when no audit
    service is wired (e.g. unit tests using a stub container)."""
    if audit_service is None:
        return
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=action,
        entity_type=entity_type,
        entity_id=target.id,
        description=description,
        metadata=AuditMetadata.standard(
            actor=user, target=target, changes=changes, extra=extra
        ),
    )


class _DeletedSnapshot:
    """Tiny carrier for `id` + `name` of a row about to be deleted, kept
    around so audit metadata can reference it after the SQLAlchemy session
    has already detached the original."""

    __slots__ = ("id", "name")

    def __init__(self, id: UUID, name: str) -> None:
        self.id = id
        self.name = name


# ---------------------------------------------------------------------------
# Completion
# ---------------------------------------------------------------------------


class TenantCompletionModelService:
    def __init__(
        self,
        session: "AsyncSession",
        user: "UserInDB",
        audit_service: "AuditService | None" = None,
    ) -> None:
        self.session = session
        self.user = user
        self.audit_service = audit_service

    async def create(self, payload: "TenantCompletionModelCreate") -> "CompletionModel":
        provider = await _validate_active_provider(
            self.session, payload.provider_id, self.user.tenant_id
        )
        await _validate_unique_display_name(
            self.session,
            CompletionModels,
            tenant_id=self.user.tenant_id,
            provider_id=payload.provider_id,
            nickname=payload.display_name,
        )

        if payload.is_default:
            await _unset_other_defaults(
                self.session, CompletionModels, self.user.tenant_id
            )

        classification_id = await resolve_tenant_security_classification(
            self.session, payload.security_classification, self.user.tenant_id
        )

        # Attribute-by-attribute assignment because SQLAlchemy's legacy
        # `Column`-style ORM models don't expose a typed constructor — the
        # equivalent kwargs call would need a blanket type-ignore.
        new_model = CompletionModels()
        new_model.tenant_id = self.user.tenant_id
        new_model.provider_id = payload.provider_id
        new_model.name = payload.name
        new_model.nickname = payload.display_name
        # Built at runtime by TenantModelAdapter from provider_type + name.
        new_model.litellm_model_name = None
        new_model.max_input_tokens = payload.max_input_tokens
        new_model.max_output_tokens = payload.max_output_tokens
        new_model.vision = payload.vision
        new_model.reasoning = payload.reasoning
        new_model.supports_tool_calling = payload.supports_tool_calling
        new_model.family = payload.family
        new_model.hosting = payload.hosting
        new_model.org = None
        new_model.stability = "stable"
        new_model.open_source = False
        new_model.description = payload.description
        new_model.nr_billion_parameters = None
        new_model.hf_link = None
        new_model.is_deprecated = False
        new_model.deployment_name = None
        new_model.base_url = None
        new_model.model_kwargs_capabilities = (
            payload.model_kwargs_capabilities.model_dump()
            if payload.model_kwargs_capabilities is not None
            else _snapshot_completion_capabilities(
                provider.provider_type,
                payload.name,
                reasoning=payload.reasoning,
            )
        )
        new_model.input_cost_per_token = payload.input_cost_per_token
        new_model.output_cost_per_token = payload.output_cost_per_token
        new_model.is_enabled = payload.is_active
        new_model.is_default = payload.is_default
        new_model.security_classification_id = classification_id
        self.session.add(new_model)
        await self.session.flush()

        repo = CompletionModelRepository(self.session, self.user)
        loaded = await repo.one(model_id=new_model.id)

        await _audit(
            self.audit_service,
            user=self.user,
            action=ActionType.COMPLETION_MODEL_CREATED,
            entity_type=EntityType.COMPLETION_MODEL,
            target=loaded,
            description=f"Created tenant completion model {loaded.name}",
            extra={"provider_id": str(payload.provider_id)},
        )
        return loaded

    async def update(
        self, model_id: UUID, payload: "TenantCompletionModelUpdate"
    ) -> "CompletionModel":
        stmt = sa.select(CompletionModels).where(
            CompletionModels.id == model_id,
            CompletionModels.tenant_id == self.user.tenant_id,
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        if not model:
            raise NotFoundException(
                "Model not found or does not belong to your organization"
            )
        _ensure_tenant_owned(model)

        provided = payload.model_fields_set
        if payload.name is not None:
            model.name = payload.name
        if payload.display_name is not None:
            await _validate_unique_display_name(
                self.session,
                CompletionModels,
                tenant_id=self.user.tenant_id,
                provider_id=model.provider_id,
                nickname=payload.display_name,
                exclude_id=model.id,
            )
            model.nickname = payload.display_name
        if "description" in provided:
            model.description = payload.description
        if payload.max_input_tokens is not None:
            model.max_input_tokens = payload.max_input_tokens
        if payload.max_output_tokens is not None:
            model.max_output_tokens = payload.max_output_tokens
        if payload.vision is not None:
            model.vision = payload.vision
        if payload.reasoning is not None:
            model.reasoning = payload.reasoning
        if payload.supports_tool_calling is not None:
            model.supports_tool_calling = payload.supports_tool_calling
        if payload.hosting is not None:
            model.hosting = payload.hosting
        if payload.open_source is not None:
            model.open_source = payload.open_source
        if payload.stability is not None:
            model.stability = payload.stability
        if "input_cost_per_token" in provided:
            model.input_cost_per_token = payload.input_cost_per_token
        if "output_cost_per_token" in provided:
            model.output_cost_per_token = payload.output_cost_per_token
        # Name or reasoning changes invalidate the stored capability snapshot;
        # re-discover with both fields settled. An explicit capability payload
        # below still wins over the refreshed snapshot.
        if payload.name is not None or payload.reasoning is not None:
            if model.provider_id is None:
                raise BadRequestException(
                    "Tenant completion model is missing its provider"
                )
            provider_repo = ModelProviderRepository(
                session=self.session,
                tenant_id=self.user.tenant_id,
            )
            provider = await provider_repo.get_by_id(model.provider_id)
            model.model_kwargs_capabilities = _snapshot_completion_capabilities(
                provider.provider_type,
                model.name,
                reasoning=model.reasoning,
            )
        if "model_kwargs_capabilities" in provided:
            model.model_kwargs_capabilities = (
                payload.model_kwargs_capabilities.model_dump()
                if payload.model_kwargs_capabilities is not None
                else None
            )
        if "is_default" in provided and payload.is_default is not None:
            if payload.is_default:
                await _unset_other_defaults(
                    self.session, CompletionModels, self.user.tenant_id
                )
            model.is_default = payload.is_default
        if "security_classification" in provided:
            model.security_classification_id = (
                await resolve_tenant_security_classification(
                    self.session,
                    payload.security_classification,
                    self.user.tenant_id,
                )
            )

        await self.session.flush()

        repo = CompletionModelRepository(self.session, self.user)
        loaded = await repo.one(model_id=model.id)

        await _audit(
            self.audit_service,
            user=self.user,
            action=ActionType.COMPLETION_MODEL_UPDATED,
            entity_type=EntityType.COMPLETION_MODEL,
            target=loaded,
            description=f"Updated tenant completion model {loaded.name}",
            extra={"fields": sorted(provided)},
        )
        return loaded

    async def delete(self, model_id: UUID) -> None:
        from eneo.ai_models.completion_models.completion_models_repo import (
            CompletionModelsRepository,
        )

        stmt = sa.select(CompletionModels).where(
            CompletionModels.id == model_id,
            CompletionModels.tenant_id == self.user.tenant_id,
            CompletionModels.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        if not model:
            raise NotFoundException(
                "Model not found or does not belong to your organization"
            )
        _ensure_tenant_owned(model)

        repo = CompletionModelsRepository(session=self.session)
        if await repo.has_active_references(model_id, tenant_id=self.user.tenant_id):
            raise ModelInUseException()

        await repo.delete_model(model_id)

        await _audit(
            self.audit_service,
            user=self.user,
            action=ActionType.COMPLETION_MODEL_DELETED,
            entity_type=EntityType.COMPLETION_MODEL,
            target=model,
            description=f"Deleted tenant completion model {model.name}",
        )


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------


class TenantEmbeddingModelService:
    def __init__(
        self,
        session: "AsyncSession",
        user: "UserInDB",
        audit_service: "AuditService | None" = None,
    ) -> None:
        self.session = session
        self.user = user
        self.audit_service = audit_service

    async def create(self, payload: "TenantEmbeddingModelCreate") -> "EmbeddingModel":
        await _validate_active_provider(
            self.session, payload.provider_id, self.user.tenant_id
        )
        await _validate_unique_display_name(
            self.session,
            EmbeddingModels,
            tenant_id=self.user.tenant_id,
            provider_id=payload.provider_id,
            nickname=payload.display_name,
        )

        if payload.is_default:
            await _unset_other_defaults(
                self.session, EmbeddingModels, self.user.tenant_id
            )

        classification_id = await resolve_tenant_security_classification(
            self.session, payload.security_classification, self.user.tenant_id
        )

        new_model = EmbeddingModels(
            **dict(  # type: ignore[call-arg]
                tenant_id=self.user.tenant_id,
                provider_id=payload.provider_id,
                name=payload.name,
                litellm_model_name=None,
                dimensions=payload.dimensions,
                max_input=payload.max_input,
                family=payload.family,
                hosting=payload.hosting,
                org=None,
                stability="stable",
                open_source=False,
                nickname=payload.display_name,
                description=payload.description,
                hf_link=None,
                is_deprecated=False,
                max_batch_size=None,
                input_cost_per_token=payload.input_cost_per_token,
                output_cost_per_token=payload.output_cost_per_token,
                is_enabled=payload.is_active,
                is_default=payload.is_default,
                security_classification_id=classification_id,
            )
        )
        self.session.add(new_model)
        await self.session.flush()

        repo = EmbeddingModelRepository(self.session, self.user)
        loaded = await repo.one(new_model.id)

        await _audit(
            self.audit_service,
            user=self.user,
            action=ActionType.EMBEDDING_MODEL_CREATED,
            entity_type=EntityType.EMBEDDING_MODEL,
            target=loaded,
            description=f"Created tenant embedding model {loaded.name}",
            extra={"provider_id": str(payload.provider_id)},
        )
        return loaded

    async def update(
        self, model_id: UUID, payload: "TenantEmbeddingModelUpdate"
    ) -> "EmbeddingModel":
        stmt = sa.select(EmbeddingModels).where(
            EmbeddingModels.id == model_id,
            EmbeddingModels.tenant_id == self.user.tenant_id,
            EmbeddingModels.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        if not model:
            raise NotFoundException(
                "Model not found or does not belong to your organization"
            )
        _ensure_tenant_owned(model)

        provided = payload.model_fields_set
        if payload.display_name is not None:
            await _validate_unique_display_name(
                self.session,
                EmbeddingModels,
                tenant_id=self.user.tenant_id,
                provider_id=model.provider_id,
                nickname=payload.display_name,
                exclude_id=model.id,
            )
            model.nickname = payload.display_name
        if "description" in provided:
            model.description = payload.description
        if payload.family is not None:
            model.family = payload.family
        if "dimensions" in provided:
            model.dimensions = payload.dimensions
        if "max_input" in provided:
            model.max_input = payload.max_input
        if payload.hosting is not None:
            model.hosting = payload.hosting
        if payload.open_source is not None:
            model.open_source = payload.open_source
        if payload.stability is not None:
            model.stability = payload.stability
        if "input_cost_per_token" in provided:
            model.input_cost_per_token = payload.input_cost_per_token
        if "output_cost_per_token" in provided:
            model.output_cost_per_token = payload.output_cost_per_token
        if "is_default" in provided and payload.is_default is not None:
            if payload.is_default:
                await _unset_other_defaults(
                    self.session, EmbeddingModels, self.user.tenant_id
                )
            model.is_default = payload.is_default
        if "security_classification" in provided:
            model.security_classification_id = (
                await resolve_tenant_security_classification(
                    self.session,
                    payload.security_classification,
                    self.user.tenant_id,
                )
            )

        await self.session.flush()

        repo = EmbeddingModelRepository(self.session, self.user)
        loaded = await repo.one(model.id)

        await _audit(
            self.audit_service,
            user=self.user,
            action=ActionType.EMBEDDING_MODEL_UPDATED,
            entity_type=EntityType.EMBEDDING_MODEL,
            target=loaded,
            description=f"Updated tenant embedding model {loaded.name}",
            extra={"fields": sorted(provided)},
        )
        return loaded

    async def delete(self, model_id: UUID) -> None:
        from eneo.database.tables.collections_table import CollectionsTable
        from eneo.database.tables.integration_table import IntegrationKnowledge
        from eneo.database.tables.spaces_table import SpacesEmbeddingModels
        from eneo.database.tables.websites_table import Websites

        stmt = sa.select(EmbeddingModels).where(
            EmbeddingModels.id == model_id,
            EmbeddingModels.tenant_id == self.user.tenant_id,
            EmbeddingModels.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        if not model:
            raise NotFoundException(
                "Model not found or does not belong to your organization"
            )
        _ensure_tenant_owned(model)

        usage_counts = await self.session.execute(
            sa.select(
                sa.select(sa.func.count())
                .where(CollectionsTable.embedding_model_id == model_id)
                .correlate(None)
                .scalar_subquery()
                .label("collections"),
                sa.select(sa.func.count())
                .where(Websites.embedding_model_id == model_id)
                .correlate(None)
                .scalar_subquery()
                .label("websites"),
                sa.select(sa.func.count())
                .where(IntegrationKnowledge.embedding_model_id == model_id)
                .correlate(None)
                .scalar_subquery()
                .label("integrations"),
            )
        )
        row = usage_counts.one()
        if row.collections > 0 or row.websites > 0 or row.integrations > 0:
            raise ModelInUseException()

        # Spaces are containers (configuration, not usage): drop the link rows so
        # the soft-deleted model doesn't dangle in space-aware reads.
        await self.session.execute(
            sa.delete(SpacesEmbeddingModels).where(
                SpacesEmbeddingModels.embedding_model_id == model_id
            )
        )

        # Soft delete: keep the row as a tombstone so historical info_blob chunks
        # (FK ON DELETE SET NULL) keep resolving their embedding model. Read paths
        # filter deleted_at; the cleanup worker hard-deletes once nothing
        # references it.
        snapshot = _DeletedSnapshot(id=model.id, name=model.name)
        model.deleted_at = sa.func.now()
        await self.session.flush()

        await _audit(
            self.audit_service,
            user=self.user,
            action=ActionType.EMBEDDING_MODEL_DELETED,
            entity_type=EntityType.EMBEDDING_MODEL,
            target=snapshot,
            description=f"Deleted tenant embedding model {snapshot.name}",
        )


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------


class TenantTranscriptionModelService:
    def __init__(
        self,
        session: "AsyncSession",
        user: "UserInDB",
        audit_service: "AuditService | None" = None,
    ) -> None:
        self.session = session
        self.user = user
        self.audit_service = audit_service

    async def create(
        self, payload: "TenantTranscriptionModelCreate"
    ) -> "TranscriptionModel":
        await _validate_active_provider(
            self.session, payload.provider_id, self.user.tenant_id
        )
        await _validate_unique_display_name(
            self.session,
            TranscriptionModels,
            tenant_id=self.user.tenant_id,
            provider_id=payload.provider_id,
            nickname=payload.display_name,
        )

        if payload.is_default:
            await _unset_other_defaults(
                self.session, TranscriptionModels, self.user.tenant_id
            )

        classification_id = await resolve_tenant_security_classification(
            self.session, payload.security_classification, self.user.tenant_id
        )

        new_model = TranscriptionModels(
            **dict(  # type: ignore[call-arg]
                tenant_id=self.user.tenant_id,
                provider_id=payload.provider_id,
                name=payload.display_name,
                # Keep nickname in sync with the display name (which still lives
                # in `name` for transcription). Lets the read path source the
                # display from nickname uniformly with completion/embedding.
                nickname=payload.display_name,
                model_name=payload.name,
                family=payload.family,
                hosting=payload.hosting,
                org=None,
                stability="stable",
                open_source=False,
                description=payload.description,
                hf_link=None,
                is_deprecated=False,
                base_url="",
                cost_per_minute=payload.cost_per_minute,
                is_enabled=payload.is_active,
                is_default=payload.is_default,
                security_classification_id=classification_id,
            )
        )
        self.session.add(new_model)
        await self.session.flush()

        repo = TranscriptionModelRepository(self.session, self.user)
        loaded = await repo.one(new_model.id)

        await _audit(
            self.audit_service,
            user=self.user,
            action=ActionType.TRANSCRIPTION_MODEL_CREATED,
            entity_type=EntityType.TRANSCRIPTION_MODEL,
            target=loaded,
            description=f"Created tenant transcription model {loaded.name}",
            extra={"provider_id": str(payload.provider_id)},
        )
        return loaded

    async def update(
        self, model_id: UUID, payload: "TenantTranscriptionModelUpdate"
    ) -> "TranscriptionModel":
        stmt = sa.select(TranscriptionModels).where(
            TranscriptionModels.id == model_id,
            TranscriptionModels.tenant_id == self.user.tenant_id,
            TranscriptionModels.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        if not model:
            raise NotFoundException(
                "Model not found or does not belong to your organization"
            )
        _ensure_tenant_owned(model)

        provided = payload.model_fields_set
        if payload.display_name is not None:
            await _validate_unique_display_name(
                self.session,
                TranscriptionModels,
                tenant_id=self.user.tenant_id,
                provider_id=model.provider_id,
                nickname=payload.display_name,
                exclude_id=model.id,
            )
            model.name = payload.display_name
            model.nickname = payload.display_name
        if "description" in provided:
            model.description = payload.description
        if payload.hosting is not None:
            model.hosting = payload.hosting
        if payload.open_source is not None:
            model.open_source = payload.open_source
        if payload.stability is not None:
            model.stability = payload.stability
        if "cost_per_minute" in provided:
            model.cost_per_minute = payload.cost_per_minute
        if "is_default" in provided and payload.is_default is not None:
            if payload.is_default:
                await _unset_other_defaults(
                    self.session, TranscriptionModels, self.user.tenant_id
                )
            model.is_default = payload.is_default
        if "security_classification" in provided:
            model.security_classification_id = (
                await resolve_tenant_security_classification(
                    self.session,
                    payload.security_classification,
                    self.user.tenant_id,
                )
            )

        await self.session.flush()

        repo = TranscriptionModelRepository(self.session, self.user)
        loaded = await repo.one(model.id)

        await _audit(
            self.audit_service,
            user=self.user,
            action=ActionType.TRANSCRIPTION_MODEL_UPDATED,
            entity_type=EntityType.TRANSCRIPTION_MODEL,
            target=loaded,
            description=f"Updated tenant transcription model {loaded.name}",
            extra={"fields": sorted(provided)},
        )
        return loaded

    async def delete(self, model_id: UUID) -> None:
        from eneo.database.tables.app_table import Apps
        from eneo.database.tables.spaces_table import SpacesTranscriptionModels

        stmt = sa.select(TranscriptionModels).where(
            TranscriptionModels.id == model_id,
            TranscriptionModels.tenant_id == self.user.tenant_id,
            TranscriptionModels.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        if not model:
            raise NotFoundException(
                "Model not found or does not belong to your organization"
            )
        _ensure_tenant_owned(model)

        # Block while any app still transcribes with this model. The FK is
        # ON DELETE SET NULL, so a hard delete would silently null those apps'
        # transcription_model_id instead of failing — an explicit count is the
        # only thing standing between deletion and orphaned apps.
        app_refs = await self.session.scalar(
            sa.select(sa.func.count())
            .select_from(Apps)
            .where(Apps.transcription_model_id == model_id)
        )
        if app_refs:
            raise ModelInUseException()

        # Spaces are containers: a model "enabled" on a space without an app
        # using it is configuration, not usage. Drop those cross-reference rows
        # so the soft-deleted model doesn't dangle in space-aware reads (which
        # join on the link table rather than filter deleted_at).
        await self.session.execute(
            sa.delete(SpacesTranscriptionModels).where(
                SpacesTranscriptionModels.transcription_model_id == model_id
            )
        )

        # Soft delete: keep the row as a tombstone so migration history and any
        # lingering references still resolve. Read paths filter deleted_at; the
        # cleanup worker hard-deletes once nothing references it.
        snapshot = _DeletedSnapshot(id=model.id, name=model.name)
        model.deleted_at = sa.func.now()
        await self.session.flush()

        await _audit(
            self.audit_service,
            user=self.user,
            action=ActionType.TRANSCRIPTION_MODEL_DELETED,
            entity_type=EntityType.TRANSCRIPTION_MODEL,
            target=snapshot,
            description=f"Deleted tenant transcription model {snapshot.name}",
        )
