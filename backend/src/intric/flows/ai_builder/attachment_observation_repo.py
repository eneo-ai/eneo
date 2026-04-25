"""Tenant-scoped cache access for `builder_attachment_observations`.

Isolates row-level access (lookup, upsert, LRU prune) away from
`AIBuilderRepository` so the cache layer stays small and independently
testable. Cache identity is the composite primary key `(tenant_id,
content_sha256, digest_version, fcm_version, pattern_registry_version)`
— any version bump invalidates prior rows.

`last_accessed_at` is the LRU timestamp: every cache hit bumps it so
the per-tenant prune keeps the ten thousand most-recently-used rows.
Prune runs on demand from the upsert path; a dedicated eviction job
is deferred until a tenant actually approaches the cap.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.tables.flow_tables import BuilderAttachmentObservations
from intric.flows.ai_builder.attachment_observation import (
    AttachmentObservation,
    DeterministicSignals,
)

DEFAULT_PER_TENANT_CAP: int = 10_000


class AttachmentObservationRepo:
    """Row-level access for the attachment-observation cache."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(
        self,
        *,
        tenant_id: UUID,
        content_sha256: str,
        digest_version: int,
        fcm_version: int,
        pattern_registry_version: int,
    ) -> AttachmentObservation | None:
        """Return the cached observation or ``None``.

        Touches `last_accessed_at` on a hit so LRU prune reflects
        recent use. Misses do not open a transaction or mutate anything.
        """
        stmt = select(
            BuilderAttachmentObservations.observation_json,
        ).where(
            BuilderAttachmentObservations.tenant_id == tenant_id,
            BuilderAttachmentObservations.content_sha256 == content_sha256,
            BuilderAttachmentObservations.digest_version == digest_version,
            BuilderAttachmentObservations.fcm_version == fcm_version,
            BuilderAttachmentObservations.pattern_registry_version
            == pattern_registry_version,
        )
        row = (await self.session.execute(stmt)).first()
        if row is None:
            return None

        observation_json: dict[str, Any] = row[0]
        await self._touch_accessed(
            tenant_id=tenant_id,
            content_sha256=content_sha256,
            digest_version=digest_version,
            fcm_version=fcm_version,
            pattern_registry_version=pattern_registry_version,
        )
        return AttachmentObservation.model_validate(observation_json)

    async def upsert(
        self,
        *,
        observation: AttachmentObservation,
        signals: DeterministicSignals,
        per_tenant_cap: int = DEFAULT_PER_TENANT_CAP,
    ) -> None:
        """Insert or update the observation row and prune LRU overflow.

        `observation.validated_snapshot()` re-runs every validator so a
        caller that mutated the observation after construction cannot
        silently persist drifted JSONB. The prune runs after the insert
        so the row we just wrote is never the one evicted.
        """
        snapshot = observation.validated_snapshot()
        now = datetime.now(timezone.utc)
        insert_stmt = pg_insert(BuilderAttachmentObservations).values(
            tenant_id=snapshot.tenant_id,
            content_sha256=snapshot.content_sha256,
            digest_version=snapshot.digest_version,
            fcm_version=snapshot.fcm_version,
            pattern_registry_version=snapshot.pattern_registry_version,
            observation_json=snapshot.model_dump(mode="json"),
            deterministic_signals_json=signals.model_dump(mode="json"),
            created_at=now,
            last_accessed_at=now,
        )
        upsert_stmt = insert_stmt.on_conflict_do_update(
            constraint="pk_builder_attachment_observations",
            set_={
                "observation_json": insert_stmt.excluded.observation_json,
                "deterministic_signals_json": (
                    insert_stmt.excluded.deterministic_signals_json
                ),
                "last_accessed_at": insert_stmt.excluded.last_accessed_at,
            },
        )
        await self.session.execute(upsert_stmt)
        await self._prune_over_cap(
            tenant_id=snapshot.tenant_id,
            per_tenant_cap=per_tenant_cap,
        )

    async def _touch_accessed(
        self,
        *,
        tenant_id: UUID,
        content_sha256: str,
        digest_version: int,
        fcm_version: int,
        pattern_registry_version: int,
    ) -> None:
        now = datetime.now(timezone.utc)
        stmt = (
            sa.update(BuilderAttachmentObservations)
            .where(
                BuilderAttachmentObservations.tenant_id == tenant_id,
                BuilderAttachmentObservations.content_sha256 == content_sha256,
                BuilderAttachmentObservations.digest_version == digest_version,
                BuilderAttachmentObservations.fcm_version == fcm_version,
                BuilderAttachmentObservations.pattern_registry_version
                == pattern_registry_version,
            )
            .values(last_accessed_at=now)
        )
        await self.session.execute(stmt)

    async def _prune_over_cap(
        self,
        *,
        tenant_id: UUID,
        per_tenant_cap: int,
    ) -> None:
        """Delete oldest rows beyond the per-tenant LRU cap.

        A no-op when the tenant has `<= per_tenant_cap` rows. The
        targeted subquery materialises only the overflow row keys so
        the delete never scans the full table.
        """
        count_stmt = (
            select(sa.func.count())
            .select_from(BuilderAttachmentObservations)
            .where(BuilderAttachmentObservations.tenant_id == tenant_id)
        )
        current_count = (await self.session.execute(count_stmt)).scalar_one()
        if current_count <= per_tenant_cap:
            return

        overflow = int(current_count) - per_tenant_cap
        overflow_ids = (
            select(
                BuilderAttachmentObservations.tenant_id,
                BuilderAttachmentObservations.content_sha256,
                BuilderAttachmentObservations.digest_version,
                BuilderAttachmentObservations.fcm_version,
                BuilderAttachmentObservations.pattern_registry_version,
            )
            .where(BuilderAttachmentObservations.tenant_id == tenant_id)
            .order_by(BuilderAttachmentObservations.last_accessed_at.asc())
            .limit(overflow)
            .subquery()
        )
        delete_stmt = sa.delete(BuilderAttachmentObservations).where(
            sa.tuple_(
                BuilderAttachmentObservations.tenant_id,
                BuilderAttachmentObservations.content_sha256,
                BuilderAttachmentObservations.digest_version,
                BuilderAttachmentObservations.fcm_version,
                BuilderAttachmentObservations.pattern_registry_version,
            ).in_(
                select(
                    overflow_ids.c.tenant_id,
                    overflow_ids.c.content_sha256,
                    overflow_ids.c.digest_version,
                    overflow_ids.c.fcm_version,
                    overflow_ids.c.pattern_registry_version,
                )
            )
        )
        await self.session.execute(delete_stmt)
