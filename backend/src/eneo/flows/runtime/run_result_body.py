"""The document a ``run_result`` delivery sends: the run's text result and
every deliverable of the completed run, with each file's bytes inline.

The body is built again for every send attempt. File content lives only in
the file it came from and in the request: errors raised here name files by id,
never by their content.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping, Sequence
from uuid import UUID

from eneo.flows.api.flow_run_contract_models import FlowRunDeliverablePublic
from eneo.flows.domain.flow import FlowRun
from eneo.json_types import JsonValue

RUN_RESULT_SCHEMA = "eneo.flow_run_result.v1"
# The files of one run result together, counted before base64, which makes
# the body about a third larger. As large as one file a tool may return.
RUN_RESULT_MAX_FILE_BYTES = 20 * 1024 * 1024


def run_result_file_ids(deliverables: Sequence[FlowRunDeliverablePublic]) -> list[UUID]:
    """Every file the body sends, in body order."""
    return [file.file_id for deliverable in deliverables for file in deliverable.files]


def check_run_result_files(deliverables: Sequence[FlowRunDeliverablePublic]) -> None:
    """Refuse, before any content is read, a body that could only be sent in
    part or that is larger than the cap. Every refusal is permanent."""
    files = [file for deliverable in deliverables for file in deliverable.files]
    unavailable = [str(file.file_id) for file in files if not file.content_available]
    if unavailable:
        raise ValueError(
            "Run result delivery has deliverable files whose content is no longer "
            f"stored: {', '.join(unavailable)}."
        )
    total = sum(file.size for file in files)
    if total > RUN_RESULT_MAX_FILE_BYTES:
        raise ValueError(
            f"Run result delivery files hold {total} bytes, more than the "
            f"{RUN_RESULT_MAX_FILE_BYTES} bytes one result may send."
        )


def run_result_body(
    *,
    run: FlowRun,
    text: str,
    deliverables: Sequence[FlowRunDeliverablePublic],
    contents: Mapping[UUID, bytes],
) -> JsonValue:
    """The run's finished result, as the receiver gets it. ``contents`` holds
    each file's stored bytes; a file whose bytes are missing or no longer
    match its checksum refuses the whole body."""
    if run.finished_at is None:
        raise ValueError(
            "Run result delivery found a completed run without a finish time."
        )
    return {
        "schema": RUN_RESULT_SCHEMA,
        "flow_id": str(run.flow_id),
        "run_id": str(run.id),
        "run_created_at": run.created_at.isoformat(),
        "run_completed_at": run.finished_at.isoformat(),
        "text": text,
        "deliverables": [
            {
                "kind": deliverable.kind,
                "step_id": str(deliverable.step_id),
                "step_order": deliverable.step_order,
                "label": deliverable.label,
                "output_type": deliverable.output_type.value,
                "files": [
                    {
                        "file_id": str(file.file_id),
                        "name": file.name,
                        "mimetype": file.mimetype,
                        "size": file.size,
                        "checksum": file.checksum,
                        "content_base64": _content_base64(
                            file.file_id,
                            content=contents.get(file.file_id),
                            size=file.size,
                            checksum=file.checksum,
                        ),
                    }
                    for file in deliverable.files
                ],
            }
            for deliverable in deliverables
        ],
    }


def _content_base64(
    file_id: UUID, *, content: bytes | None, size: int, checksum: str
) -> str:
    if content is None:
        raise ValueError(f"Run result delivery could not read file {file_id}.")
    if len(content) != size or hashlib.sha256(content).hexdigest() != checksum:
        raise ValueError(
            f"Run result delivery file {file_id} no longer matches its checksum."
        )
    return base64.b64encode(content).decode("ascii")
