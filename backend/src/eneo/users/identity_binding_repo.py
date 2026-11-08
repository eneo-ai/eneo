"""The provider identities bound to accounts, and the two ways to re-bind.

``UserService.resolve_federated_user`` owns the decision; this module stores
it. A binding is unique per (tenant, issuer, audience, subject) and per
(account, issuer, audience). Inserts never raise on a lost race: they insert
nothing and the caller re-reads.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from eneo.database.database import AsyncSession
from eneo.database.tables.identity_bindings_table import (
    IdentityBindings,
    IdentityMigrationWindows,
)
from eneo.database.tables.users_table import Users
from eneo.main.exceptions import FederatedLoginDenied


class IdentityConflictError(FederatedLoginDenied):
    """The presented identity cannot be bound to the account its email names
    (403). ``reason`` says why, for the audit and the log; the response does
    not carry it."""

    code = "identity_conflict"

    def __init__(self, reason: str):
        super().__init__(
            "This account is already linked to another sign-in. "
            "Contact your administrator."
        )
        self.reason = reason


@dataclass(frozen=True)
class IdentityBinding:
    issuer: str
    audience: str
    subject: str
    created_at: datetime


@dataclass(frozen=True)
class IdentityMigrationWindow:
    id: UUID
    from_issuer: str
    from_audience: str
    to_issuer: str
    to_audience: str
    closes_at: datetime
    created_at: datetime


_WINDOW_COLUMNS = (
    IdentityMigrationWindows.id,
    IdentityMigrationWindows.from_issuer,
    IdentityMigrationWindows.from_audience,
    IdentityMigrationWindows.to_issuer,
    IdentityMigrationWindows.to_audience,
    IdentityMigrationWindows.closes_at,
    IdentityMigrationWindows.created_at,
)


class IdentityBindingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def holder(
        self, *, tenant_id: UUID, issuer: str, audience: str, subject: str
    ) -> UUID | None:
        """The account this exact identity is bound to."""
        return await self.session.scalar(
            sa.select(IdentityBindings.user_id).where(
                IdentityBindings.tenant_id == tenant_id,
                IdentityBindings.issuer == issuer,
                IdentityBindings.subject == subject,
                IdentityBindings.audience == audience,
            )
        )

    async def holders_of_subject(
        self, *, tenant_id: UUID, issuer: str, subject: str
    ) -> list[UUID]:
        """Up to two accounts that hold this subject under any audience."""
        rows = await self.session.scalars(
            sa.select(IdentityBindings.user_id)
            .where(
                IdentityBindings.tenant_id == tenant_id,
                IdentityBindings.issuer == issuer,
                IdentityBindings.subject == subject,
            )
            .distinct()
            .limit(2)
        )
        return list(rows)

    async def of_user(self, user_id: UUID) -> list[IdentityBinding]:
        rows = await self.session.execute(
            sa.select(
                IdentityBindings.issuer,
                IdentityBindings.audience,
                IdentityBindings.subject,
                IdentityBindings.created_at,
            )
            .where(IdentityBindings.user_id == user_id)
            .order_by(IdentityBindings.created_at)
        )
        return [IdentityBinding(*row) for row in rows]

    async def bind(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        issuer: str,
        audience: str,
        subject: str,
    ) -> bool:
        """Insert the binding; False when either unique key is already taken."""
        inserted = await self.session.scalar(
            postgresql.insert(IdentityBindings)
            .values(
                tenant_id=tenant_id,
                user_id=user_id,
                issuer=issuer,
                audience=audience,
                subject=subject,
            )
            .on_conflict_do_nothing()
            .returning(IdentityBindings.id)
        )
        return inserted is not None

    async def unbind(self, *, user_id: UUID, issuer: str, audience: str) -> None:
        await self.session.execute(
            sa.delete(IdentityBindings).where(
                IdentityBindings.user_id == user_id,
                IdentityBindings.issuer == issuer,
                IdentityBindings.audience == audience,
            )
        )

    async def open_window(
        self,
        *,
        tenant_id: UUID,
        to_issuer: str,
        to_audience: str,
        from_pairs: Iterable[tuple[str, str]],
    ) -> UUID | None:
        """An open window from one of these pairs to the given one."""
        pairs = list(from_pairs)
        if not pairs:
            return None
        return await self.session.scalar(
            sa.select(IdentityMigrationWindows.id)
            .where(
                IdentityMigrationWindows.tenant_id == tenant_id,
                IdentityMigrationWindows.to_issuer == to_issuer,
                IdentityMigrationWindows.to_audience == to_audience,
                IdentityMigrationWindows.closes_at > sa.func.now(),
                sa.tuple_(
                    IdentityMigrationWindows.from_issuer,
                    IdentityMigrationWindows.from_audience,
                ).in_(pairs),
            )
            .order_by(IdentityMigrationWindows.created_at)
            .limit(1)
        )

    async def rebinding_open(self, user_id: UUID) -> bool:
        """Whether an admin's re-binding allowance for the account is open."""
        return bool(
            await self.session.scalar(
                sa.select(Users.identity_rebinding_until > sa.func.now()).where(
                    Users.id == user_id
                )
            )
        )

    async def close_rebinding(self, user_id: UUID) -> None:
        await self.session.execute(
            sa.update(Users)
            .where(Users.id == user_id, Users.identity_rebinding_until.is_not(None))
            .values(identity_rebinding_until=None)
        )

    async def rebinding_until(self, user_id: UUID) -> datetime | None:
        """The stored end of the account's allowance, even if it has passed."""
        return await self.session.scalar(
            sa.select(Users.identity_rebinding_until).where(Users.id == user_id)
        )

    async def set_rebinding(self, user_id: UUID, until: datetime | None) -> None:
        await self.session.execute(
            sa.update(Users)
            .where(Users.id == user_id)
            .values(identity_rebinding_until=until)
        )

    async def list_open_windows(self, tenant_id: UUID) -> list[IdentityMigrationWindow]:
        rows = await self.session.execute(
            sa.select(*_WINDOW_COLUMNS)
            .where(
                IdentityMigrationWindows.tenant_id == tenant_id,
                IdentityMigrationWindows.closes_at > sa.func.now(),
            )
            .order_by(IdentityMigrationWindows.created_at)
        )
        return [IdentityMigrationWindow(*row) for row in rows]

    async def add_window(
        self,
        *,
        tenant_id: UUID,
        from_issuer: str,
        from_audience: str,
        to_issuer: str,
        to_audience: str,
        closes_at: datetime,
        created_by: UUID,
    ) -> IdentityMigrationWindow:
        row = (
            await self.session.execute(
                sa.insert(IdentityMigrationWindows)
                .values(
                    tenant_id=tenant_id,
                    from_issuer=from_issuer,
                    from_audience=from_audience,
                    to_issuer=to_issuer,
                    to_audience=to_audience,
                    closes_at=closes_at,
                    created_by=created_by,
                )
                .returning(*_WINDOW_COLUMNS)
            )
        ).one()
        return IdentityMigrationWindow(*row)

    async def close_window(
        self, *, tenant_id: UUID, window_id: UUID
    ) -> IdentityMigrationWindow | None:
        """Close an open window now; None when no open one has this id."""
        row = (
            await self.session.execute(
                sa.update(IdentityMigrationWindows)
                .where(
                    IdentityMigrationWindows.id == window_id,
                    IdentityMigrationWindows.tenant_id == tenant_id,
                    IdentityMigrationWindows.closes_at > sa.func.now(),
                )
                .values(closes_at=sa.func.now())
                .returning(*_WINDOW_COLUMNS)
            )
        ).one_or_none()
        return IdentityMigrationWindow(*row) if row is not None else None
