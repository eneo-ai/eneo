from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.info_blobs.info_blob_repo import InfoBlobRepository
from eneo.main.exceptions import (
    TenantQuotaExceededException,
    UserQuotaExceededException,
)
from eneo.users.user import UserInDB

_PENDING_QUOTA_OWNERS = "knowledge_publication_quota_owners"


def enforce_quota_on_commit(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID
) -> None:
    """Validate retained storage after all publications in this transaction.

    Ingestion may publish several sources in one transaction, with provider I/O
    between them. Acquiring the quota lock at the outer commit keeps that I/O
    outside the lock and preserves the caller's atomic rollback boundary.
    """
    owners = cast(
        set[tuple[UUID, UUID]],
        session.sync_session.info.setdefault(_PENDING_QUOTA_OWNERS, set()),
    )
    owners.add((tenant_id, user_id))


def _check_publication_quota(session: Session) -> None:
    if session.in_nested_transaction():
        return
    owners = cast(
        set[tuple[UUID, UUID]], session.info.get(_PENDING_QUOTA_OWNERS, set())
    )
    if not owners:
        return

    session.flush()
    # NO KEY UPDATE coordinates quota edits and other publishers without
    # conflicting with the FK key-share locks already held by inserted rows.
    # All source locks precede these final locks; no provider work follows them.
    tenant_limits = dict(
        session.execute(
            sa.select(Tenants.id, Tenants.quota_limit)
            .where(Tenants.id.in_({tenant_id for tenant_id, _ in owners}))
            .order_by(Tenants.id)
            .with_for_update(key_share=True)
        )
        .tuples()
        .all()
    )
    user_limits = dict(
        session.execute(
            sa.select(Users.id, Users.quota_limit)
            .where(Users.id.in_({user_id for _, user_id in owners}))
            .order_by(Users.id)
            .with_for_update(key_share=True)
        )
        .tuples()
        .all()
    )
    tenant_usage = {
        tenant_id: session.scalar(
            InfoBlobRepository.retained_size_of_tenant_stmt(tenant_id)
        )
        or 0
        for tenant_id in tenant_limits
    }
    for tenant_id, user_id in sorted(owners):
        user_limit = user_limits[user_id]
        user_usage = (
            session.scalar(InfoBlobRepository.retained_size_of_user_stmt(user_id)) or 0
            if user_limit is not None
            else 0
        )
        ensure_quota_capacity(
            tenant_usage=tenant_usage[tenant_id],
            tenant_limit=tenant_limits[tenant_id],
            user_usage=user_usage,
            user_limit=user_limit,
            size_in_bytes=0,
        )


def _clear_publication_quota(session: Session, transaction: SessionTransaction) -> None:
    if transaction.parent is None:
        session.info.pop(_PENDING_QUOTA_OWNERS, None)


event.listen(Session, "before_commit", _check_publication_quota)
event.listen(Session, "after_transaction_end", _clear_publication_quota)


def ensure_quota_capacity(
    *,
    tenant_usage: int,
    tenant_limit: int,
    user_usage: int,
    user_limit: int | None,
    size_in_bytes: int,
) -> None:
    if tenant_usage + size_in_bytes > tenant_limit:
        raise TenantQuotaExceededException("Tenant quota limit exceeded.")
    if user_limit is not None and user_usage + size_in_bytes > user_limit:
        raise UserQuotaExceededException("User quota limit exceeded.")


class QuotaService:
    def __init__(self, user: UserInDB, info_blob_repo: InfoBlobRepository):
        super().__init__()
        self.user = user
        self.info_blob_repo = info_blob_repo

    def _size_of_text(self, text: str) -> int:
        return len(text.encode("utf-8"))

    async def ensure_capacity(self, size_in_bytes: int) -> None:
        tenant_usage = await self.info_blob_repo.get_retained_size_of_tenant(
            self.user.tenant.id
        )
        user_usage = (
            await self.info_blob_repo.get_retained_size_of_user(self.user.id)
            if self.user.quota_limit is not None
            else 0
        )
        ensure_quota_capacity(
            tenant_usage=tenant_usage,
            tenant_limit=self.user.tenant.quota_limit,
            user_usage=user_usage,
            user_limit=self.user.quota_limit,
            size_in_bytes=size_in_bytes,
        )

    async def add_text(self, text_to_add: str) -> int:
        size_of_text = self._size_of_text(text_to_add)
        await self.ensure_capacity(size_of_text)
        return size_of_text
