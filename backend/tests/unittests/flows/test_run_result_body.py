"""The run result body: every deliverable with its files' bytes inline, or a
permanent refusal before anything is sent."""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from eneo.files.file_models import FileType
from eneo.flows.api.flow_run_contract_models import FlowRunDeliverablePublic
from eneo.flows.enums import FlowOutputType
from eneo.flows.flow_run_step_result_file import FlowRunStepResultFile
from eneo.flows.runtime.run_result_body import (
    RUN_RESULT_MAX_FILE_BYTES,
    check_run_result_files,
    run_result_body,
    run_result_file_ids,
)

MARKER = b"MARKER-7f3c-only-in-the-document"
CONTENT = b"PK\x03\x04" + MARKER


def _file(content: bytes = CONTENT, **overrides: object) -> FlowRunStepResultFile:
    values: dict[str, object] = {
        "flow_run_id": uuid4(),
        "flow_id": uuid4(),
        "tenant_id": uuid4(),
        "step_result_id": uuid4(),
        "step_id": uuid4(),
        "step_order": 1,
        "attempt_no": 1,
        "file_id": uuid4(),
        "ordinal": 0,
        "source": "declared_artifact",
        "name": "Startsidan.docx",
        "checksum": hashlib.sha256(content).hexdigest(),
        "size": len(content),
        "mimetype": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "file_type": FileType.DOCUMENT,
        "availability": "available",
    }
    values.update(overrides)
    return FlowRunStepResultFile.model_validate(values)


def _deliverable(*files: FlowRunStepResultFile) -> FlowRunDeliverablePublic:
    return FlowRunDeliverablePublic(
        kind="artifact",
        step_id=files[0].step_id if files else uuid4(),
        step_order=1,
        label="Startsidan",
        output_type=FlowOutputType.DOCX,
        files=list(files),
    )


RUN = SimpleNamespace(
    id=UUID("00000000-0000-4000-8000-000000000001"),
    flow_id=UUID("00000000-0000-4000-8000-000000000002"),
    created_at=datetime(2026, 11, 20, 8, 0, tzinfo=timezone.utc),
    finished_at=datetime(2026, 11, 20, 8, 5, tzinfo=timezone.utc),
)


def test_each_deliverable_file_is_sent_with_its_bytes_and_checksum() -> None:
    file = _file()
    deliverable = _deliverable(file)

    body = run_result_body(
        run=RUN,  # pyright: ignore[reportArgumentType]
        text="# Möte",
        deliverables=[deliverable],
        contents={file.file_id: CONTENT},
    )

    assert body == {
        "schema": "eneo.flow_run_result.v1",
        "flow_id": str(RUN.flow_id),
        "run_id": str(RUN.id),
        "run_created_at": "2026-11-20T08:00:00+00:00",
        "run_completed_at": "2026-11-20T08:05:00+00:00",
        "text": "# Möte",
        "deliverables": [
            {
                "kind": "artifact",
                "step_id": str(deliverable.step_id),
                "step_order": 1,
                "label": "Startsidan",
                "output_type": "docx",
                "files": [
                    {
                        "file_id": str(file.file_id),
                        "name": "Startsidan.docx",
                        "mimetype": file.mimetype,
                        "size": len(CONTENT),
                        "checksum": hashlib.sha256(CONTENT).hexdigest(),
                        "content_base64": base64.b64encode(CONTENT).decode(),
                    }
                ],
            }
        ],
    }
    assert run_result_file_ids([deliverable]) == [file.file_id]


@pytest.mark.parametrize(
    ("contents", "reason"),
    [
        ({}, "could not read"),
        ({"changed": CONTENT + b"x"}, "no longer matches"),
    ],
)
def test_a_file_that_cannot_be_sent_whole_refuses_the_body(
    contents: dict[str, bytes], reason: str
) -> None:
    file = _file()
    by_id = {file.file_id: value for value in contents.values()}

    with pytest.raises(ValueError, match=reason) as refused:
        run_result_body(
            run=RUN,  # pyright: ignore[reportArgumentType]
            text="",
            deliverables=[_deliverable(file)],
            contents=by_id,
        )

    assert str(file.file_id) in str(refused.value)
    assert MARKER.decode() not in str(refused.value)


def test_a_file_whose_content_retention_removed_refuses_the_body() -> None:
    purged = _file(availability="content_purged")

    with pytest.raises(ValueError, match="no longer stored") as refused:
        check_run_result_files([_deliverable(_file(), purged)])

    assert str(purged.file_id) in str(refused.value)


def test_files_over_the_cap_refuse_the_body_before_any_is_read() -> None:
    half = RUN_RESULT_MAX_FILE_BYTES // 2 + 1
    big = [_file(size=half), _file(size=half)]

    with pytest.raises(ValueError, match="more than"):
        check_run_result_files([_deliverable(*big)])

    check_run_result_files([_deliverable(_file(size=RUN_RESULT_MAX_FILE_BYTES))])


def test_a_deliverable_without_a_file_refuses_the_body() -> None:
    """A marked document the run did not produce would be sent as an empty
    group, and the receiver would take a part of the result for all of it."""
    empty = _deliverable()

    with pytest.raises(ValueError, match="has no file") as refused:
        check_run_result_files([_deliverable(_file()), empty])

    assert str(empty.step_id) in str(refused.value)
    # A run that marks no document sends its text alone.
    check_run_result_files([])
