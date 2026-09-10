from collections.abc import Collection, Mapping
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from eneo.database.tables.ai_models_table import EmbeddingModels
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.info_blobs_table import InfoBlobs
from eneo.database.tables.integration_table import IntegrationKnowledge
from eneo.database.tables.model_providers_table import ModelProviders
from eneo.database.tables.security_classifications_table import SecurityClassification
from eneo.database.tables.websites_table import Websites
from eneo.embedding_models.domain.embedding_model import EmbeddingModel
from eneo.main.exceptions import ModelInUseException, NotFoundException

if TYPE_CHECKING:
    from uuid import UUID

    from eneo.database.database import AsyncSession
    from eneo.users.user import UserInDB


_EMBEDDING_SEMANTIC_FIELDS = frozenset(
    {
        "name",
        "litellm_model_name",
        "family",
        "dimensions",
        "max_input",
        "provider_id",
    }
)


async def require_unused_embedding_models(
    session: "AsyncSession", model_ids: Collection["UUID"]
) -> None:
    """Check configuration and retained vectors while model rows are locked."""
    if not model_ids:
        return
    referenced = await session.scalar(
        sa.select(
            sa.or_(
                sa.exists().where(CollectionsTable.embedding_model_id.in_(model_ids)),
                sa.exists().where(Websites.embedding_model_id.in_(model_ids)),
                sa.exists().where(
                    IntegrationKnowledge.embedding_model_id.in_(model_ids)
                ),
                sa.exists().where(InfoBlobs.embedding_model_id.in_(model_ids)),
            )
        )
    )
    if referenced:
        raise ModelInUseException(
            "This embedding configuration is used by knowledge or retained versions. "
            "Create a new embedding model and reindex the knowledge to change it."
        )


async def guard_embedding_model_update(
    session: "AsyncSession", model_id: "UUID", changes: Mapping[str, object]
) -> None:
    fields = _EMBEDDING_SEMANTIC_FIELDS.intersection(changes)
    if not fields:
        return
    model = await session.scalar(
        sa.select(EmbeddingModels)
        .where(EmbeddingModels.id == model_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    # FOR UPDATE conflicts with the FK key-share lock of a new assignment.
    # Read usage after obtaining it, so a racing first assignment is visible.
    if model is not None and any(
        getattr(model, field) != changes[field] for field in fields
    ):
        await require_unused_embedding_models(session, [model_id])


async def guard_embedding_provider_update(
    session: "AsyncSession", provider_id: "UUID"
) -> None:
    """Freeze the route of every used embedding model on a locked provider."""
    model_ids = list(
        await session.scalars(
            sa.select(EmbeddingModels.id)
            .where(EmbeddingModels.provider_id == provider_id)
            .order_by(EmbeddingModels.id)
            .with_for_update()
        )
    )
    await require_unused_embedding_models(session, model_ids)


class EmbeddingModelRepository:
    def __init__(self, session: "AsyncSession", user: "UserInDB") -> None:
        super().__init__()
        self.session = session
        self.user = user

    async def all(self, with_deprecated: bool = False):
        stmt = (
            sa.select(
                EmbeddingModels, ModelProviders.name, ModelProviders.provider_type
            )
            .outerjoin(ModelProviders, EmbeddingModels.provider_id == ModelProviders.id)
            .options(
                selectinload(EmbeddingModels.security_classification),
                selectinload(EmbeddingModels.security_classification).options(
                    selectinload(SecurityClassification.tenant)
                ),
            )
            .where(
                # Return both global and tenant models
                # This allows existing collections with global models to continue working
                # UI filtering happens at the presentation layer
                sa.or_(
                    EmbeddingModels.tenant_id.is_(None),
                    EmbeddingModels.tenant_id == self.user.tenant_id,
                ),
                # Soft-deleted models are tombstones kept only so existing
                # collections/websites still resolve; never surface them.
                EmbeddingModels.deleted_at.is_(None),
            )
            .order_by(
                EmbeddingModels.org,
                EmbeddingModels.created_at,
                EmbeddingModels.name,
            )
        )

        if not with_deprecated:
            stmt = stmt.where(EmbeddingModels.is_deprecated == False)  # noqa

        result = await self.session.execute(stmt)
        rows = result.all()

        return [
            EmbeddingModel.to_domain(
                db_model=embedding_model,
                user=self.user,
                provider_name=provider_name,
                provider_type=provider_type,
            )
            for embedding_model, provider_name, provider_type in rows
        ]

    async def one_or_none(self, model_id: "UUID") -> Optional["EmbeddingModel"]:
        # When fetching by ID, return ANY model (global or tenant) that the user can access
        stmt = (
            sa.select(
                EmbeddingModels, ModelProviders.name, ModelProviders.provider_type
            )
            .outerjoin(ModelProviders, EmbeddingModels.provider_id == ModelProviders.id)
            .options(
                selectinload(EmbeddingModels.security_classification),
                selectinload(EmbeddingModels.security_classification).options(
                    selectinload(SecurityClassification.tenant)
                ),
            )
            .where(
                EmbeddingModels.id == model_id,
                # Allow both global models (tenant_id IS NULL) and tenant models (tenant_id = user.tenant_id)
                sa.or_(
                    EmbeddingModels.tenant_id.is_(None),
                    EmbeddingModels.tenant_id == self.user.tenant_id,
                ),
                # Soft-deleted models stay invisible to all callers.
                EmbeddingModels.deleted_at.is_(None),
            )
        )

        result = await self.session.execute(stmt)
        row = result.one_or_none()

        if row is None:
            return

        embedding_model, provider_name, provider_type = row
        return EmbeddingModel.to_domain(
            db_model=embedding_model,
            user=self.user,
            provider_name=provider_name,
            provider_type=provider_type,
        )

    async def one(self, model_id: "UUID") -> "EmbeddingModel":
        embedding_model = await self.one_or_none(model_id=model_id)

        if embedding_model is None:
            raise NotFoundException()

        return embedding_model

    async def update(self, embedding_model: "EmbeddingModel"):
        # Update settings directly on the model table
        security_classification_id = (
            embedding_model.security_classification.id
            if embedding_model.security_classification
            else None
        )

        stmt = (
            sa.update(EmbeddingModels)
            .values(
                is_enabled=embedding_model.is_org_enabled,
                security_classification_id=security_classification_id,
            )
            .where(
                EmbeddingModels.id == embedding_model.id,
                EmbeddingModels.tenant_id == self.user.tenant_id,
            )
        )
        await self.session.execute(stmt)

        return await self.one(model_id=embedding_model.id)
