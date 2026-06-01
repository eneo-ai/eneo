# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

from typing import TYPE_CHECKING, Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from typing_extensions import override

from intric.base.base_repository import BaseRepository
from intric.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassificationDBModel,
)
from intric.main.exceptions import NotFoundException
from intric.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)
from intric.users.user import UserInDB

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SecurityClassificationRepoImpl(BaseRepository):
    """Implementation of the security classification repository interface."""

    def __init__(self, session: "AsyncSession", user: UserInDB) -> None:
        super().__init__()
        self.session = session
        self.user = user

    @override
    async def all(self) -> list[SecurityClassification]:  # type: ignore[override]  # covariant narrowing: list[SecurityClassification] ⊄ list[Entity] (invariant list)
        query = (
            select(SecurityClassificationDBModel)
            .where(SecurityClassificationDBModel.tenant_id == self.user.tenant_id)
            .order_by(SecurityClassificationDBModel.security_level)
            .options(selectinload(SecurityClassificationDBModel.tenant))
        )
        result = await self.session.scalars(query)
        records = result.all()

        return [
            sc
            for record in records
            if (
                sc := SecurityClassification.to_domain(
                    db_security_classification=record
                )
            )
            is not None
        ]

    @override
    async def one(self, id: UUID) -> SecurityClassification:
        security_classification = await self.one_or_none(id)
        if not security_classification:
            raise NotFoundException(f"Security classification with ID {id} not found")
        return security_classification

    @override
    async def one_or_none(self, id: UUID) -> Optional[SecurityClassification]:
        query = (
            select(SecurityClassificationDBModel)
            .where(
                sa.and_(
                    SecurityClassificationDBModel.id == id,
                    SecurityClassificationDBModel.tenant_id == self.user.tenant_id,
                )
            )
            .options(selectinload(SecurityClassificationDBModel.tenant))
        )
        result = await self.session.scalar(query)

        if not result:
            return None

        return SecurityClassification.to_domain(db_security_classification=result)

    @override
    async def add(  # type: ignore[override]  # narrower param name (security_classification vs entity); both accept SecurityClassification
        self, security_classification: SecurityClassification
    ) -> SecurityClassification:
        values = {
            "name": security_classification.name,
            "description": security_classification.description,
            "security_level": security_classification.security_level,
            "tenant_id": self.user.tenant_id,
        }

        query = (
            sa.insert(SecurityClassificationDBModel)
            .values(**values)
            .returning(SecurityClassificationDBModel)
        )
        result = await self.session.execute(query)
        record = result.scalar_one()

        # After insertion, query for the record with tenant loaded
        return await self.one(record.id)

    @override
    async def update(  # type: ignore[override]  # narrower param name (security_classification vs entity); both accept SecurityClassification
        self, security_classification: SecurityClassification
    ) -> SecurityClassification:
        assert security_classification.id is not None, (
            "Security classification must have an ID to update"
        )

        # Convert domain entity to db values
        values = {
            "name": security_classification.name,
            "description": security_classification.description,
            "security_level": security_classification.security_level,
        }

        # Update the database with tenant check in the WHERE clause
        query = (
            sa.update(SecurityClassificationDBModel)
            .where(
                sa.and_(
                    SecurityClassificationDBModel.id == security_classification.id,
                    SecurityClassificationDBModel.tenant_id == self.user.tenant_id,
                )
            )
            .values(**values)
            .returning(SecurityClassificationDBModel)
        )

        result = await self.session.execute(query)
        record = result.scalar_one_or_none()

        # If no record was found/updated (wrong ID or wrong tenant), raise exception
        if record is None:
            raise NotFoundException(
                f"Security classification with ID {security_classification.id} not found"
            )

        # Query for the record with tenant loaded
        return await self.one(record.id)

    async def count_usages(self, id: UUID) -> dict[str, int]:
        """Count how many rows currently reference this classification.

        Used by the service before deletion: a classification's FK is
        `ON DELETE SET NULL`, so dropping a row in active use would
        silently relabel every model / space / MCP server that referenced
        it as "no classification". For a system whose whole point is
        to gate model availability by classification, that's a privilege
        escalation by accident — the admin sees "1 row deleted" while
        actually loosening access on N other rows.
        """
        from intric.database.tables.ai_models_table import (
            CompletionModels,
            EmbeddingModels,
            TranscriptionModels,
        )
        from intric.database.tables.mcp_server_table import MCPServers
        from intric.database.tables.spaces_table import Spaces

        # Soft-deleted completion models still carry their FK to the
        # classification, but they're not active anymore — counting them
        # produces an "in use" error the admin can't act on. Embedding /
        # transcription models have no soft-delete column today.
        counts = await self.session.execute(
            sa.select(
                sa.select(sa.func.count())
                .where(
                    CompletionModels.security_classification_id == id,
                    CompletionModels.deleted_at.is_(None),
                )
                .scalar_subquery()
                .label("completion_models"),
                sa.select(sa.func.count())
                .where(EmbeddingModels.security_classification_id == id)
                .scalar_subquery()
                .label("embedding_models"),
                sa.select(sa.func.count())
                .where(TranscriptionModels.security_classification_id == id)
                .scalar_subquery()
                .label("transcription_models"),
                sa.select(sa.func.count())
                .where(Spaces.security_classification_id == id)
                .scalar_subquery()
                .label("spaces"),
                sa.select(sa.func.count())
                .where(MCPServers.security_classification_id == id)
                .scalar_subquery()
                .label("mcp_servers"),
            )
        )
        row = counts.one()
        return {
            "completion_models": row.completion_models,
            "embedding_models": row.embedding_models,
            "transcription_models": row.transcription_models,
            "spaces": row.spaces,
            "mcp_servers": row.mcp_servers,
        }

    @override
    async def delete(self, id: UUID) -> None:
        query = (
            sa.delete(SecurityClassificationDBModel)
            .where(
                sa.and_(
                    SecurityClassificationDBModel.id == id,
                    SecurityClassificationDBModel.tenant_id == self.user.tenant_id,
                )
            )
            .returning(SecurityClassificationDBModel.id)
        )

        result = await self.session.execute(query)
        deleted_id = result.scalar_one_or_none()

        # If no record was deleted (wrong ID or wrong tenant), raise exception
        if deleted_id is None:
            raise NotFoundException(f"Security classification with ID {id} not found")
