from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from intric.authentication.auth_models import ApiKeyScopeType, ApiKeyState, ApiKeyV2InDB
from intric.database.tables.api_keys_v2_table import ApiKeysV2
from intric.database.tables.users_table import Users


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
        key_prefix: Optional[str] = None,
        tenant_id: UUID | None = None,
    ) -> Optional[ApiKeyV2InDB]:
        query = sa.select(self.table).where(self.table.key_hash == key_hash)
        if hash_version is not None:
            query = query.where(self.table.hash_version == hash_version)
        if key_prefix is not None:
            query = query.where(self.table.key_prefix == key_prefix)
        if tenant_id is not None:
            query = query.where(self.table.tenant_id == tenant_id)
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
        owner_user_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
        search: str | None = None,
        expires_within_days: int | None = None,
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
            owner_user_id=owner_user_id,
            created_by_user_id=created_by_user_id,
            search=search,
            expires_within_days=expires_within_days,
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

    async def list_filtered(
        self,
        *,
        tenant_id: UUID,
        scope_type: ApiKeyScopeType | None = None,
        scope_id: UUID | None = None,
        state: ApiKeyState | None = None,
        key_type: str | None = None,
        owner_user_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
        search: str | None = None,
        expires_within_days: int | None = None,
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
            owner_user_id=owner_user_id,
            created_by_user_id=created_by_user_id,
            search=search,
            expires_within_days=expires_within_days,
        )
        query = query.order_by(self.table.created_at.desc())
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
        owner_user_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
        search: str | None = None,
        expires_within_days: int | None = None,
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
            owner_user_id=owner_user_id,
            created_by_user_id=created_by_user_id,
            search=search,
            expires_within_days=expires_within_days,
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
        owner_user_id: UUID | None,
        created_by_user_id: UUID | None,
        search: str | None,
        expires_within_days: int | None,
    ) -> Select[Any]:
        if scope_type is not None:
            query = query.where(self.table.scope_type == scope_type.value)
        if scope_id is not None:
            query = query.where(self.table.scope_id == scope_id)
        if state is not None:
            if state == ApiKeyState.EXPIRED:
                # Also match keys where expires_at has passed but the
                # async maintenance job hasn't updated state yet.
                query = query.where(
                    sa.or_(
                        self.table.state == state.value,
                        sa.and_(
                            self.table.expires_at.is_not(None),
                            self.table.expires_at <= sa.func.now(),
                            self.table.revoked_at.is_(None),
                        ),
                    )
                )
            else:
                query = query.where(self.table.state == state.value)
        if key_type is not None:
            query = query.where(self.table.key_type == key_type)
        if owner_user_id is not None:
            query = query.where(self.table.owner_user_id == owner_user_id)
        if created_by_user_id is not None:
            query = query.where(self.table.created_by_user_id == created_by_user_id)
        if expires_within_days is not None:
            horizon = datetime.now(timezone.utc) + timedelta(days=expires_within_days)
            query = query.where(self.table.expires_at.is_not(None)).where(
                self.table.expires_at <= horizon
            )
        if search is not None:
            term = f"%{search.strip().lower()}%"
            owner_match = (
                sa.select(sa.literal(1))
                .select_from(Users)
                .where(Users.id == self.table.owner_user_id)
                .where(
                    sa.or_(
                        sa.func.lower(sa.func.coalesce(Users.email, "")).like(term),
                        sa.func.lower(sa.func.coalesce(Users.username, "")).like(term),
                    )
                )
                .exists()
            )
            creator_match = (
                sa.select(sa.literal(1))
                .select_from(Users)
                .where(Users.id == self.table.created_by_user_id)
                .where(
                    sa.or_(
                        sa.func.lower(sa.func.coalesce(Users.email, "")).like(term),
                        sa.func.lower(sa.func.coalesce(Users.username, "")).like(term),
                    )
                )
                .exists()
            )
            query = query.where(
                sa.or_(
                    sa.func.lower(self.table.name).like(term),
                    sa.func.lower(self.table.key_suffix).like(term),
                    sa.func.lower(sa.func.coalesce(self.table.description, "")).like(term),
                    owner_match,
                    creator_match,
                )
            )
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

    async def list_expiring_soon(
        self,
        *,
        tenant_id: UUID,
        now: datetime,
        days: int = 30,
        limit: int = 10,
        followed_key_ids: list[UUID] | None = None,
        followed_assistant_scope_ids: list[UUID] | None = None,
        followed_app_scope_ids: list[UUID] | None = None,
        followed_space_scope_ids: list[UUID] | None = None,
    ) -> tuple[list[ApiKeyV2InDB], int]:
        """Return keys expiring within `days` or expired within the last 30 days.

        Uses durable fields (revoked_at, expires_at) instead of derived ``state``
        to avoid dependency on the maintenance job.

        Returns ``(items, total_count)`` where items is capped at ``limit``
        and ordered: expired first, then urgent, warning, notice — nearest
        expiry first within each tier.
        """
        lookback = now - timedelta(days=30)
        horizon = now + timedelta(days=days)

        base_where = [
            self.table.tenant_id == tenant_id,
            self.table.revoked_at.is_(None),
            self.table.expires_at.is_not(None),
            self.table.expires_at >= lookback,
            self.table.expires_at <= horizon,
        ]

        followed_filters_provided = any(
            values is not None
            for values in (
                followed_key_ids,
                followed_assistant_scope_ids,
                followed_app_scope_ids,
                followed_space_scope_ids,
            )
        )
        if followed_filters_provided:
            target_filters: list[Any] = []
            if followed_key_ids:
                target_filters.append(self.table.id.in_(followed_key_ids))
            if followed_assistant_scope_ids:
                target_filters.append(
                    sa.and_(
                        self.table.scope_type == ApiKeyScopeType.ASSISTANT.value,
                        self.table.scope_id.in_(followed_assistant_scope_ids),
                    )
                )
            if followed_app_scope_ids:
                target_filters.append(
                    sa.and_(
                        self.table.scope_type == ApiKeyScopeType.APP.value,
                        self.table.scope_id.in_(followed_app_scope_ids),
                    )
                )
            if followed_space_scope_ids:
                target_filters.append(
                    sa.and_(
                        self.table.scope_type == ApiKeyScopeType.SPACE.value,
                        self.table.scope_id.in_(followed_space_scope_ids),
                    )
                )

            if not target_filters:
                return [], 0

            base_where.append(sa.or_(*target_filters))

        # Total count (uncapped)
        count_query = (
            sa.select(sa.func.count())
            .select_from(self.table)
            .where(*base_where)
        )
        total = int(await self.session.scalar(count_query) or 0)

        # Items: order by severity (expired first), then nearest expiry
        # CASE: expired (<= now) → 0, urgent (<=3d) → 1, warning (<=14d) → 2, notice → 3
        urgent_bound = now + timedelta(days=3)
        warning_bound = now + timedelta(days=14)
        severity_order = sa.case(
            (self.table.expires_at <= now, 0),
            (self.table.expires_at <= urgent_bound, 1),
            (self.table.expires_at <= warning_bound, 2),
            else_=3,
        )
        items_query = (
            sa.select(self.table)
            .where(*base_where)
            .order_by(severity_order.asc(), self.table.expires_at.asc())
            .limit(limit)
        )
        records = await self.session.scalars(items_query)
        items = [ApiKeyV2InDB.model_validate(record) for record in records]

        return items, total

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
