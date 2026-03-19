# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

from typing import TYPE_CHECKING, Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

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

    def __init__(self, session: "AsyncSession", user: UserInDB):
        self.session = session
        self.user = user

    async def all(self) -> list[SecurityClassification]:
        query = (
            select(SecurityClassificationDBModel)
            .where(SecurityClassificationDBModel.tenant_id == self.user.tenant_id)
            .order_by(SecurityClassificationDBModel.security_level)
            .options(selectinload(SecurityClassificationDBModel.tenant))
        )
        result = await self.session.scalars(query)
        records = result.all()

        return [  # type: ignore[return-value]
            SecurityClassification.to_domain(db_security_classification=record)
            for record in records
        ]

    async def one(self, id: UUID) -> SecurityClassification:
        security_classification = await self.one_or_none(id)
        if not security_classification:
            raise NotFoundException(f"Security classification with ID {id} not found")
        return security_classification

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

    async def add(
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

    async def update(
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
