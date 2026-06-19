"""Build and persist flow step input-file rows for run creation and reruns."""

from __future__ import annotations

from typing import Sequence, TypedDict
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.tables.flow_tables import FlowRunStepInputFiles
from intric.flows.domain.run_step_input_exceptions import (
    FlowRunRuntimeUploadBindingRaceError,
)
from intric.flows.flow_run_step_inputs import FlowRunStepInputFileProjection
from intric.flows.flow_runtime_file_integrity import (
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
