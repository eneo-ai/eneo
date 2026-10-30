"""The suggestions a flow's editors dismissed, tenant-scoped.

Every statement names the tenant and the flow. A dismissal is written once
per flow and fingerprint (the unique key on tenant, flow and fingerprint):
a second dismissal of the same suggestion finds the first.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.flow_tables import FlowSuggestionDismissals
from eneo.flows.domain.flow_suggestion_dismissal import FlowSuggestionDismissal

_UNIQUE = "uq_flow_suggestion_dismissals_tenant_flow_fingerprint"
_COLUMNS = (
    FlowSuggestionDismissals.fingerprint,
    FlowSuggestionDismissals.code,
    FlowSuggestionDismissals.dismissed_by,
    FlowSuggestionDismissals.dismissed_at,
)


class FlowSuggestionDismissalRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_for_flow(
        self, *, flow_id: UUID, tenant_id: UUID
    ) -> dict[str, FlowSuggestionDismissal]:
        """The flow's dismissals, by fingerprint."""
        rows = (
            await self.session.execute(
                sa.select(*_COLUMNS)
                .where(FlowSuggestionDismissals.tenant_id == tenant_id)
                .where(FlowSuggestionDismissals.flow_id == flow_id)
            )
        ).all()
        return {row.fingerprint: _dismissal(row) for row in rows}

    async def add(
        self,
        *,
        flow_id: UUID,
        tenant_id: UUID,
        fingerprint: str,
        code: str,
        dismissed_by: UUID | None,
    ) -> tuple[FlowSuggestionDismissal, bool]:
        """The flow's dismissal of ``fingerprint``, written unless there is
        one, and whether this call wrote it."""
        written = (
            await self.session.execute(
                pg_insert(FlowSuggestionDismissals)
                .values(
                    tenant_id=tenant_id,
                    flow_id=flow_id,
                    fingerprint=fingerprint,
                    code=code,
                    dismissed_by=dismissed_by,
                )
                .on_conflict_do_nothing(constraint=_UNIQUE)
                .returning(*_COLUMNS)
            )
        ).one_or_none()
        if written is not None:
            return _dismissal(written), True
        existing = await self.get(
            flow_id=flow_id, tenant_id=tenant_id, fingerprint=fingerprint
        )
        assert existing is not None, "a conflicting dismissal exists"
        return existing, False

    async def get(
        self, *, flow_id: UUID, tenant_id: UUID, fingerprint: str
    ) -> FlowSuggestionDismissal | None:
        row = (
            await self.session.execute(
                sa.select(*_COLUMNS)
                .where(FlowSuggestionDismissals.tenant_id == tenant_id)
                .where(FlowSuggestionDismissals.flow_id == flow_id)
                .where(FlowSuggestionDismissals.fingerprint == fingerprint)
            )
        ).one_or_none()
        return _dismissal(row) if row is not None else None

    async def remove(
        self, *, flow_id: UUID, tenant_id: UUID, fingerprint: str
    ) -> FlowSuggestionDismissal | None:
        """Delete the flow's dismissal of ``fingerprint``; the dismissal it
        deleted, None when there was none."""
        row = (
            await self.session.execute(
                sa.delete(FlowSuggestionDismissals)
                .where(FlowSuggestionDismissals.tenant_id == tenant_id)
                .where(FlowSuggestionDismissals.flow_id == flow_id)
                .where(FlowSuggestionDismissals.fingerprint == fingerprint)
                .returning(*_COLUMNS)
            )
        ).one_or_none()
        return _dismissal(row) if row is not None else None


def _dismissal(row: Any) -> FlowSuggestionDismissal:
    return FlowSuggestionDismissal(
        fingerprint=row.fingerprint,
        code=row.code,
        dismissed_by=row.dismissed_by,
        dismissed_at=row.dismissed_at,
    )


__all__ = ["FlowSuggestionDismissalRepository"]
