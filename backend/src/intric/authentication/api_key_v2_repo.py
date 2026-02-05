from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from intric.authentication.auth_models import ApiKeyScopeType, ApiKeyState, ApiKeyV2InDB
from intric.database.tables.api_keys_v2_table import ApiKeysV2


class ApiKeysV2Repository:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.table = ApiKeysV2

    async def create(self, **values: object) -> ApiKeyV2InDB:
        query = sa.insert(self.table).values(**values).returning(self.table)
        record = await self.session.scalar(query)

        return ApiKeyV2InDB.model_validate(record)

    async def get(self, *, key_id: UUID, tenant_id: UUID) -> Optional[ApiKeyV2InDB]:
        query = (
            sa.select(self.table)
            .where(self.table.id == key_id)
            .where(self.table.tenant_id == tenant_id)
        )
        record = await self.session.scalar(query)

        if record is None:
            return None

        return ApiKeyV2InDB.model_validate(record)

    async def get_by_hash(
        self,
        *,
        key_hash: str,
        hash_version: Optional[str] = None,
    ) -> Optional[ApiKeyV2InDB]:
        query = sa.select(self.table).where(self.table.key_hash == key_hash)
        if hash_version is not None:
            query = query.where(self.table.hash_version == hash_version)
        record = await self.session.scalar(query)

        if record is None:
            return None

        return ApiKeyV2InDB.model_validate(record)

    async def list_by_scope(
        self,
        *,
        tenant_id: UUID,
        scope_type: Optional[ApiKeyScopeType] = None,
        scope_id: Optional[UUID] = None,
    ) -> list[ApiKeyV2InDB]:
        query = sa.select(self.table).where(self.table.tenant_id == tenant_id)
        if scope_type is not None:
            query = query.where(self.table.scope_type == scope_type)
        if scope_id is not None:
            query = query.where(self.table.scope_id == scope_id)
        query = query.order_by(self.table.created_at.desc())

        records = await self.session.scalars(query)

        return [ApiKeyV2InDB.model_validate(record) for record in records]

    async def list_paginated(
        self,
        *,
        tenant_id: UUID,
        limit: int | None = None,
        cursor: datetime | None = None,
        previous: bool = False,
        scope_type: ApiKeyScopeType | None = None,
        scope_id: UUID | None = None,
        state: ApiKeyState | None = None,
        key_type: str | None = None,
        created_by_user_id: UUID | None = None,
    ) -> list[ApiKeyV2InDB]:
        query = cast(
            Select[Any],
            sa.select(self.table).where(self.table.tenant_id == tenant_id),
        )
        query = self._apply_filters(
            query,
            scope_type=scope_type,
            scope_id=scope_id,
            state=state,
            key_type=key_type,
            created_by_user_id=created_by_user_id,
        )
        if cursor is not None:
            if previous:
                query = query.where(self.table.created_at > cursor)
            else:
                query = query.where(self.table.created_at < cursor)

        if previous:
            query = query.order_by(self.table.created_at.asc())
        else:
            query = query.order_by(self.table.created_at.desc())

        if limit is not None:
            query = query.limit(limit + 1)

        records = await self.session.scalars(query)
        return [ApiKeyV2InDB.model_validate(record) for record in records]

    async def count(
        self,
        *,
        tenant_id: UUID,
        scope_type: ApiKeyScopeType | None = None,
        scope_id: UUID | None = None,
        state: ApiKeyState | None = None,
        key_type: str | None = None,
        created_by_user_id: UUID | None = None,
    ) -> int:
        query = cast(
            Select[Any],
            sa.select(sa.func.count())
            .select_from(self.table)
            .where(self.table.tenant_id == tenant_id),
        )
        query = self._apply_filters(
            query,
            scope_type=scope_type,
            scope_id=scope_id,
            state=state,
            key_type=key_type,
            created_by_user_id=created_by_user_id,
        )
        result = await self.session.scalar(query)
        return int(result or 0)

    def _apply_filters(
        self,
        query: Select[Any],
        *,
        scope_type: ApiKeyScopeType | None,
        scope_id: UUID | None,
        state: ApiKeyState | None,
        key_type: str | None,
        created_by_user_id: UUID | None,
    ) -> Select[Any]:
        if scope_type is not None:
            query = query.where(self.table.scope_type == scope_type.value)
        if scope_id is not None:
            query = query.where(self.table.scope_id == scope_id)
        if state is not None:
            query = query.where(self.table.state == state.value)
        if key_type is not None:
            query = query.where(self.table.key_type == key_type)
        if created_by_user_id is not None:
            query = query.where(self.table.created_by_user_id == created_by_user_id)
        return query

    async def get_latest_active_by_owner(
        self,
        *,
        tenant_id: UUID,
        owner_user_id: UUID,
    ) -> Optional[ApiKeyV2InDB]:
        now = datetime.now(timezone.utc)
        query = (
            sa.select(self.table)
            .where(self.table.tenant_id == tenant_id)
            .where(self.table.owner_user_id == owner_user_id)
            .where(self.table.state == ApiKeyState.ACTIVE.value)
            .where(self.table.revoked_at.is_(None))
            .where(self.table.suspended_at.is_(None))
            .where(sa.or_(self.table.expires_at.is_(None), self.table.expires_at > now))
            .order_by(self.table.created_at.desc())
            .limit(1)
        )
        record = await self.session.scalar(query)
        if record is None:
            return None

        return ApiKeyV2InDB.model_validate(record)

    async def update(
        self, *, key_id: UUID, tenant_id: UUID, **values: object
    ) -> Optional[ApiKeyV2InDB]:
        if not values:
            return await self.get(key_id=key_id, tenant_id=tenant_id)

        query = (
            sa.update(self.table)
            .where(self.table.id == key_id)
            .where(self.table.tenant_id == tenant_id)
            .values(**values)
            .returning(self.table)
        )
        record = await self.session.scalar(query)

        if record is None:
            return None

        return ApiKeyV2InDB.model_validate(record)

    async def update_last_used_at(
        self,
        *,
        key_id: UUID,
        tenant_id: UUID,
        last_used_at: datetime,
        min_interval_seconds: int,
    ) -> Optional[ApiKeyV2InDB]:
        cutoff = last_used_at - timedelta(seconds=min_interval_seconds)

        query = (
            sa.update(self.table)
            .where(self.table.id == key_id)
            .where(self.table.tenant_id == tenant_id)
            .where(
                sa.or_(
                    self.table.last_used_at.is_(None),
                    self.table.last_used_at < cutoff,
                )
            )
            .values(last_used_at=last_used_at)
            .returning(self.table)
        )
        record = await self.session.scalar(query)

        if record is None:
            return None

        return ApiKeyV2InDB.model_validate(record)

    async def list_expired_candidates(
        self,
        *,
        now: datetime,
    ) -> list[ApiKeyV2InDB]:
        query = (
            sa.select(self.table)
            .where(self.table.expires_at.is_not(None))
            .where(self.table.expires_at <= now)
            .where(self.table.revoked_at.is_(None))
            .where(self.table.state != ApiKeyState.EXPIRED.value)
        )
        records = await self.session.scalars(query)
        return [ApiKeyV2InDB.model_validate(record) for record in records]

    async def list_rotation_grace_candidates(
        self,
        *,
        now: datetime,
    ) -> list[ApiKeyV2InDB]:
        query = (
            sa.select(self.table)
            .where(self.table.rotation_grace_until.is_not(None))
            .where(self.table.rotation_grace_until <= now)
            .where(self.table.revoked_at.is_(None))
            .where(self.table.state != ApiKeyState.REVOKED.value)
        )
        records = await self.session.scalars(query)
        return [ApiKeyV2InDB.model_validate(record) for record in records]

    async def list_unused_before(
        self,
        *,
        tenant_id: UUID,
        cutoff: datetime,
    ) -> list[ApiKeyV2InDB]:
        query = (
            sa.select(self.table)
            .where(self.table.tenant_id == tenant_id)
            .where(self.table.revoked_at.is_(None))
            .where(self.table.state != ApiKeyState.EXPIRED.value)
            .where(
                sa.or_(
                    self.table.last_used_at < cutoff,
                    sa.and_(
                        self.table.last_used_at.is_(None),
                        self.table.created_at < cutoff,
                    ),
                )
            )
        )
        records = await self.session.scalars(query)
        return [ApiKeyV2InDB.model_validate(record) for record in records]
