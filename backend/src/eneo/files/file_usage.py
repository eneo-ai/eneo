from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import BindParameter
from sqlalchemy.sql.selectable import Select

from eneo.database.tables.app_table import AppRunsFiles, AppsFiles
from eneo.database.tables.assistant_table import AssistantsFiles
from eneo.database.tables.files_table import Files
from eneo.database.tables.questions_table import QuestionsFiles
from eneo.files.file_models import FileUsageKind


class FileFamilyTenantMismatchError(RuntimeError):
    """A derived File points across the root File's tenant boundary."""


@dataclass(frozen=True, slots=True)
class FileUsageCount:
    kind: FileUsageKind
    count: int


class FileUsageRepository:
    """Derive usage that fences user-initiated File deletion.

    User and tenant offboarding intentionally keep their database-owned cascade
    behavior. Advisory previews use a recursive CTE, while deletion locks base
    File rows level by level because PostgreSQL 13 does not propagate an outer
    ``FOR UPDATE`` through a recursive CTE.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_family(
        self,
        *,
        root_file_id: UUID,
        tenant_id: UUID,
    ) -> list[UUID]:
        family = (
            sa.select(Files.id, Files.parent_file_id, Files.tenant_id)
            .where(Files.id == root_file_id)
            .cte("file_family", recursive=True)
        )
        descendants = sa.select(
            Files.id,
            Files.parent_file_id,
            Files.tenant_id,
        ).join(family, Files.parent_file_id == family.c.id)
        family = family.union(descendants)

        rows = (
            await self._session.execute(
                sa.select(family.c.id, family.c.tenant_id).order_by(family.c.id)
            )
        ).all()
        self._require_tenant(
            (row.tenant_id for row in rows),
            tenant_id=tenant_id,
        )
        return [row.id for row in rows]

    async def lock_family(
        self,
        *,
        root_file_id: UUID,
        tenant_id: UUID,
    ) -> list[UUID]:
        root = (
            await self._session.execute(
                sa.select(Files.id, Files.tenant_id)
                .where(Files.id == root_file_id)
                .with_for_update(of=Files)
            )
        ).one_or_none()
        if root is None:
            return []
        self._require_tenant([root.tenant_id], tenant_id=tenant_id)

        family_ids = [root.id]
        visited = {root.id}
        frontier = [root.id]
        while frontier:
            rows = (
                await self._session.execute(
                    sa.select(Files.id, Files.tenant_id)
                    .where(Files.parent_file_id.in_(frontier))
                    .order_by(Files.id)
                    .with_for_update(of=Files)
                )
            ).all()
            self._require_tenant(
                (row.tenant_id for row in rows),
                tenant_id=tenant_id,
            )
            frontier = [row.id for row in rows if row.id not in visited]
            visited.update(frontier)
            family_ids.extend(frontier)

        return family_ids

    async def count_product_usage(
        self,
        file_ids: list[UUID],
    ) -> list[FileUsageCount]:
        if not file_ids:
            return []

        file_ids_parameter = sa.bindparam(
            "file_usage_ids",
            type_=ARRAY(PostgreSQLUUID(as_uuid=True)),
        )
        usage = sa.union_all(
            self._usage_select(
                FileUsageKind.CHAT_ATTACHMENT,
                QuestionsFiles.file_id,
                file_ids_parameter,
            ),
            self._usage_select(
                FileUsageKind.ASSISTANT_ATTACHMENT,
                AssistantsFiles.file_id,
                file_ids_parameter,
            ),
            self._usage_select(
                FileUsageKind.APP_ATTACHMENT,
                AppsFiles.file_id,
                file_ids_parameter,
            ),
            self._usage_select(
                FileUsageKind.APP_RUN_INPUT,
                AppRunsFiles.file_id,
                file_ids_parameter,
            ),
        ).subquery("file_product_usage")
        rows = (
            await self._session.execute(
                sa.select(
                    usage.c.kind,
                    sa.func.count().label("usage_count"),
                )
                .group_by(usage.c.kind)
                .order_by(usage.c.kind),
                {"file_usage_ids": file_ids},
            )
        ).all()
        return [
            FileUsageCount(
                kind=FileUsageKind(row.kind),
                count=row.usage_count,
            )
            for row in rows
        ]

    @staticmethod
    def _usage_select(
        kind: FileUsageKind,
        file_id_column: InstrumentedAttribute[UUID],
        file_ids_parameter: BindParameter[Sequence[UUID]],
    ) -> Select[tuple[str, UUID]]:
        return sa.select(
            sa.literal(kind.value).label("kind"),
            file_id_column.label("file_id"),
        ).where(file_id_column == sa.any_(file_ids_parameter))

    @staticmethod
    def _require_tenant(
        tenant_ids: Iterable[UUID],
        *,
        tenant_id: UUID,
    ) -> None:
        if any(row_tenant_id != tenant_id for row_tenant_id in tenant_ids):
            raise FileFamilyTenantMismatchError(
                "Derived File family crosses a tenant boundary."
            )
