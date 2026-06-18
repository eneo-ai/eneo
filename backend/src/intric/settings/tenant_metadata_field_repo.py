from typing import Never
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from intric.database.database import AsyncSession
from intric.database.repositories.base import BaseRepositoryDelegate
from intric.database.tables.tenant_metadata_field_table import TenantMetadataFields
from intric.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UniqueException,
)
from intric.settings.metadata_fields import (
    TenantMetadataFieldCreate,
    TenantMetadataFieldInDB,
    TenantMetadataFieldUpdate,
)


class TenantMetadataFieldRepository:
    def __init__(self, session: AsyncSession):
        self.delegate: BaseRepositoryDelegate[TenantMetadataFieldInDB] = (
            BaseRepositoryDelegate(
                session, TenantMetadataFields, TenantMetadataFieldInDB
            )
        )
        self.session = session

    @staticmethod
    def _raise_integrity_error(exc: IntegrityError) -> Never:
        details = str(exc.orig).lower() if exc.orig is not None else str(exc).lower()

        if (
            "uq_tenant_metadata_fields_tenant_name" in details
            or "duplicate key" in details
        ):
            raise UniqueException("Metadata field name already exists.") from exc

        if "label" in details and (
            "null value" in details or "not-null constraint" in details
        ):
            raise BadRequestException(
                "Tenant metadata field schema is out of date in the database. "
                "Roll back and re-run migration 202606181200."
            ) from exc

        raise exc

    async def list_by_tenant(self, tenant_id: UUID) -> list[TenantMetadataFieldInDB]:
        query = (
            sa.select(TenantMetadataFields)
            .where(TenantMetadataFields.tenant_id == tenant_id)
            .order_by(TenantMetadataFields.name.asc())
        )
        return await self.delegate.get_models_from_query(query)

    async def add(
        self, tenant_id: UUID, metadata_field: TenantMetadataFieldCreate
    ) -> TenantMetadataFieldInDB:
        query = (
            sa.insert(TenantMetadataFields)
            .values(tenant_id=tenant_id, **metadata_field.model_dump())
            .returning(TenantMetadataFields)
        )
        try:
            result = await self.session.execute(query)
        except IntegrityError as exc:
            self._raise_integrity_error(exc)
        field_in_db = result.scalar_one()
        return TenantMetadataFieldInDB.model_validate(field_in_db)

    async def update(
        self, tenant_id: UUID, metadata_field: TenantMetadataFieldUpdate
    ) -> TenantMetadataFieldInDB:
        query = (
            sa.update(TenantMetadataFields)
            .values(
                name=metadata_field.name,
                field_type=metadata_field.field_type,
                visible_on_assistants=metadata_field.visible_on_assistants,
                visible_on_spaces=metadata_field.visible_on_spaces,
            )
            .where(TenantMetadataFields.id == metadata_field.id)
            .where(TenantMetadataFields.tenant_id == tenant_id)
            .returning(TenantMetadataFields)
        )
        try:
            result = await self.session.execute(query)
        except IntegrityError as exc:
            self._raise_integrity_error(exc)
        field_in_db = result.scalar_one_or_none()
        if field_in_db is None:
            raise NotFoundException()
        return TenantMetadataFieldInDB.model_validate(field_in_db)

    async def delete(self, tenant_id: UUID, field_id: UUID) -> None:
        query = (
            sa.delete(TenantMetadataFields)
            .where(TenantMetadataFields.id == field_id)
            .where(TenantMetadataFields.tenant_id == tenant_id)
        )
        result = await self.session.execute(query)
        if result.rowcount == 0:
            raise NotFoundException()
