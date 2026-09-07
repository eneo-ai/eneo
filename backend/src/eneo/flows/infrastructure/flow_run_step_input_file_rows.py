"""Build and persist flow step input-file rows.

Run creation binds the uploads to attempt 1; a recovery attempt inherits that
binding so a retried step reads the same uploaded files.
"""

from __future__ import annotations

from typing import Sequence, TypedDict
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.flow_tables import FlowRunStepInputFiles
from eneo.flows.domain.run_step_input_exceptions import (
    FlowRunRuntimeUploadBindingRaceError,
)
from eneo.flows.flow_run_step_inputs import FlowRunStepInputFileProjection
from eneo.flows.flow_runtime_file_integrity import (
    is_runtime_upload_binding_integrity_error,
)


class FlowRunStepInputFileRow(TypedDict):
    flow_run_id: UUID
    flow_id: UUID
    tenant_id: UUID
    step_id: UUID
    step_order: int
    attempt_no: int
    file_id: UUID
    ordinal: int


def build_step_input_file_rows(
    *,
    flow_run_id: UUID,
    flow_id: UUID,
    tenant_id: UUID,
    attempt_no: int,
    projections: Sequence[FlowRunStepInputFileProjection] | None,
) -> list[FlowRunStepInputFileRow]:
    return [
        {
            "flow_run_id": flow_run_id,
            "flow_id": flow_id,
            "tenant_id": tenant_id,
            "step_id": projection["step_id"],
            "step_order": projection["step_order"],
            "attempt_no": attempt_no,
            "file_id": file_id,
            "ordinal": ordinal,
        }
        for projection in sorted(
            projections or (),
            key=lambda item: (int(item["step_order"]), str(item["step_id"])),
        )
        for ordinal, file_id in enumerate(projection["file_ids"])
    ]


async def insert_step_input_file_rows(
    *,
    session: AsyncSession,
    rows: Sequence[FlowRunStepInputFileRow],
) -> None:
    if not rows:
        return
    try:
        await session.execute(sa.insert(FlowRunStepInputFiles).values(rows))
    except IntegrityError as exc:
        if not is_runtime_upload_binding_integrity_error(exc):
            raise
        step_id, file_ids = _step_input_file_binding_race_payload(rows)
        raise FlowRunRuntimeUploadBindingRaceError(
            step_id=step_id,
            file_ids=file_ids,
        ) from exc


async def inherit_step_input_file_rows(
    *,
    session: AsyncSession,
    run_id: UUID,
    tenant_id: UUID,
    step_id: UUID,
    attempt_no: int,
) -> None:
    """Bind attempt 1's uploaded files to a later attempt of the same step.

    Idempotent under the unique constraint, so a repeated allocation of the
    same attempt number is a no-op.
    """
    select_rows = (
        sa.select(
            FlowRunStepInputFiles.flow_run_id,
            FlowRunStepInputFiles.flow_id,
            FlowRunStepInputFiles.tenant_id,
            FlowRunStepInputFiles.step_id,
            FlowRunStepInputFiles.step_order,
            sa.literal(attempt_no).label("attempt_no"),
            FlowRunStepInputFiles.file_id,
            FlowRunStepInputFiles.ordinal,
        )
        .where(FlowRunStepInputFiles.flow_run_id == run_id)
        .where(FlowRunStepInputFiles.tenant_id == tenant_id)
        .where(FlowRunStepInputFiles.step_id == step_id)
        .where(FlowRunStepInputFiles.attempt_no == 1)
    )
    await session.execute(
        pg_insert(FlowRunStepInputFiles)
        .from_select(
            [
                "flow_run_id",
                "flow_id",
                "tenant_id",
                "step_id",
                "step_order",
                "attempt_no",
                "file_id",
                "ordinal",
            ],
            select_rows,
        )
        .on_conflict_do_nothing(
            constraint="uq_flow_run_step_input_files_run_step_attempt_file",
        )
    )


def _step_input_file_binding_race_payload(
    rows: Sequence[FlowRunStepInputFileRow],
) -> tuple[UUID, tuple[UUID, ...]]:
    ordered_rows = sorted(
        rows,
        key=lambda row: (
            row["step_order"],
            str(row["step_id"]),
            row["ordinal"],
            str(row["file_id"]),
        ),
    )
    step_id = ordered_rows[0]["step_id"]
    file_ids = tuple(
        row["file_id"] for row in ordered_rows if row["step_id"] == step_id
    )
    return step_id, file_ids
