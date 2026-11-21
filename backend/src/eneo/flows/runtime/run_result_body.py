"""The document a ``run_result`` delivery sends: every deliverable of the
completed run, each text whole and each document's bytes inline.

The body is built again for every send attempt, from each deliverable's
current result in the run. Content lives only where it came from and in the
request: errors raised here name steps and files by id, never by their
content, and every one of them is permanent.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from eneo.flows.api.flow_run_contract_models import (
    FlowRunDeliverablePublic,
    FlowRunTextDeliverablePublic,
)
from eneo.flows.domain.flow import FlowRun, FlowStepResult
from eneo.flows.domain.step_output import (
    FileBackedStepText,
    StepOutputMetadataError,
    interpret_step_text,
)
from eneo.flows.flow_run_step_result_file import (
    FlowRunStepResultFile,
    text_overflow_files,
)
from eneo.json_types import JsonValue

RUN_RESULT_SCHEMA = "eneo.flow_run_result.v1"
# Texts and files of one run result together, counted before base64, which
# makes a file about a third larger. As large as one file a tool may return.
RUN_RESULT_MAX_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class RunResultText:
    """A text deliverable and where its text is: inline in the step's
    result, or whole in the step's own file when it was too long to keep
    inline. Never in a repr: it may hold the text."""

    deliverable: FlowRunTextDeliverablePublic
    inline: str | None = field(default=None, repr=False)
    file: FlowRunStepResultFile | None = None


RunResultPart = FlowRunDeliverablePublic | RunResultText


def run_result_text(
    deliverable: FlowRunTextDeliverablePublic,
    *,
    step_result: FlowStepResult | None,
    result_files: Sequence[FlowRunStepResultFile],
) -> RunResultText:
    """Where ``deliverable``'s text is in its step's current result. A text
    the result no longer holds, or a file that is not that attempt's own
    text, refuses the body; an empty text is a text."""
    step_id = deliverable.step_id
    if step_result is None or step_result.current_attempt_no is None:
        raise ValueError(f"Run result delivery has no result for step {step_id}.")
    try:
        text = interpret_step_text(step_result.output_payload_json)
    except StepOutputMetadataError as exc:
        raise ValueError(
            f"Run result delivery has no text for step {step_id}: its result "
            "holds none, or no longer does."
        ) from exc
    if not isinstance(text, FileBackedStepText):
        return RunResultText(deliverable=deliverable, inline=text.text)
    files = [
        file
        for file in text_overflow_files(
            result_files,
            run_id=step_result.flow_run_id,
            flow_id=step_result.flow_id,
            tenant_id=step_result.tenant_id,
            step_id=step_id,
            file_id=text.file_id,
        )
        if file.attempt_no == step_result.current_attempt_no
    ]
    if (
        len(files) != 1
        or files[0].size != text.full_text_bytes
        or len(files[0].checksum) != 64
    ):
        raise ValueError(
            f"Run result delivery found no file {text.file_id} that holds the "
            f"current text of step {step_id}."
        )
    if not files[0].content_available:
        raise ValueError(
            f"Run result delivery text file {text.file_id} of step {step_id} is "
            "no longer stored."
        )
    return RunResultText(deliverable=deliverable, file=files[0])


def _files(part: RunResultPart) -> list[FlowRunStepResultFile]:
    if isinstance(part, RunResultText):
        return [part.file] if part.file is not None else []
    return part.files


def run_result_file_ids(parts: Sequence[RunResultPart]) -> list[UUID]:
    """Every file the body reads, in body order."""
    return [file.file_id for part in parts for file in _files(part)]


def check_run_result(parts: Sequence[RunResultPart]) -> None:
    """Refuse, before any content is read, a body that could only be sent in
    part or that is larger than the cap."""
    empty = [
        str(part.step_id)
        for part in parts
        if isinstance(part, FlowRunDeliverablePublic) and not part.files
    ]
    if empty:
        raise ValueError(
            "Run result delivery has documents the run did not produce, from "
            f"steps {', '.join(empty)}: a document step has no file."
        )
    files = [file for part in parts for file in _files(part)]
    unavailable = [str(file.file_id) for file in files if not file.content_available]
    if unavailable:
        raise ValueError(
            "Run result delivery has deliverable files whose content is no longer "
            f"stored: {', '.join(unavailable)}."
        )
    total = sum(file.size for file in files) + sum(
        len(part.inline.encode("utf-8"))
        for part in parts
        if isinstance(part, RunResultText) and part.inline is not None
    )
    if total > RUN_RESULT_MAX_BYTES:
        raise ValueError(
            f"Run result delivery texts and files hold {total} bytes, more than "
            f"the {RUN_RESULT_MAX_BYTES} bytes one result may send."
        )


def run_result_body(
    *,
    run: FlowRun,
    parts: Sequence[RunResultPart],
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
        "deliverables": [_body_part(part, contents=contents) for part in parts],
    }


def _body_part(part: RunResultPart, *, contents: Mapping[UUID, bytes]) -> JsonValue:
    if isinstance(part, RunResultText):
        deliverable = part.deliverable
        return {
            "kind": "text",
            "step_id": str(deliverable.step_id),
            "step_order": deliverable.step_order,
            "label": deliverable.label,
            "output_type": deliverable.output_type.value,
            "text": (
                part.inline
                if part.file is None
                else _file_text(part.file, content=contents.get(part.file.file_id))
            ),
        }
    return {
        "kind": part.kind,
        "step_id": str(part.step_id),
        "step_order": part.step_order,
        "label": part.label,
        "output_type": part.output_type.value,
        "files": [
            {
                "file_id": str(file.file_id),
                "name": file.name,
                "mimetype": file.mimetype,
                "size": file.size,
                "checksum": file.checksum,
                "content_base64": base64.b64encode(
                    _checked(file, content=contents.get(file.file_id))
                ).decode("ascii"),
            }
            for file in part.files
        ],
    }


def _file_text(file: FlowRunStepResultFile, *, content: bytes | None) -> str:
    try:
        return _checked(file, content=content).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"Run result delivery text file {file.file_id} is not UTF-8."
        ) from exc


def _checked(file: FlowRunStepResultFile, *, content: bytes | None) -> bytes:
    if content is None:
        raise ValueError(f"Run result delivery could not read file {file.file_id}.")
    if (
        len(content) != file.size
        or hashlib.sha256(content).hexdigest() != file.checksum
    ):
        raise ValueError(
            f"Run result delivery file {file.file_id} no longer matches its checksum."
        )
    return content
