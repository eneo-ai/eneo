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
from eneo.flows.api.flow_run_contract_models import (
    FlowRunDeliverablePublic,
    FlowRunTextDeliverablePublic,
)
from eneo.flows.domain.flow import FlowStepResult, FlowStepResultStatus
from eneo.flows.enums import FlowOutputType
from eneo.flows.flow_run_step_result_file import FlowRunStepResultFile
from eneo.flows.http_transport import EffectiveHttpRequest
from eneo.flows.runtime.flow_webhook_delivery import WebhookDeliveryPayload
from eneo.flows.runtime.run_result_body import (
    RUN_RESULT_MAX_BYTES,
    RunResultText,
    check_run_result,
    run_result_body,
    run_result_file_ids,
    run_result_text,
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
        parts=[deliverable],
        contents={file.file_id: CONTENT},
    )

    assert body == {
        "schema": "eneo.flow_run_result.v1",
        "flow_id": str(RUN.flow_id),
        "run_id": str(RUN.id),
        "run_created_at": "2026-11-20T08:00:00+00:00",
        "run_completed_at": "2026-11-20T08:05:00+00:00",
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
            parts=[_deliverable(file)],
            contents=by_id,
        )

    assert str(file.file_id) in str(refused.value)
    assert MARKER.decode() not in str(refused.value)


def test_a_file_whose_content_retention_removed_refuses_the_body() -> None:
    purged = _file(availability="content_purged")

    with pytest.raises(ValueError, match="no longer stored") as refused:
        check_run_result([_deliverable(_file(), purged)])

    assert str(purged.file_id) in str(refused.value)


def test_files_over_the_cap_refuse_the_body_before_any_is_read() -> None:
    half = RUN_RESULT_MAX_BYTES // 2 + 1
    big = [_file(size=half), _file(size=half)]

    with pytest.raises(ValueError, match="more than"):
        check_run_result([_deliverable(*big)])

    check_run_result([_deliverable(_file(size=RUN_RESULT_MAX_BYTES))])


def test_a_deliverable_without_a_file_refuses_the_body() -> None:
    """A marked document the run did not produce would be sent as an empty
    group, and the receiver would take a part of the result for all of it."""
    empty = _deliverable()

    with pytest.raises(ValueError, match="has no file") as refused:
        check_run_result([_deliverable(_file()), empty])

    assert str(empty.step_id) in str(refused.value)


def test_a_body_with_file_content_never_appears_in_a_repr() -> None:
    """A request or payload that reaches a log or an error report through its
    repr carries no file content."""
    body = {"content_base64": base64.b64encode(CONTENT).decode()}
    request = EffectiveHttpRequest(
        method="POST",
        url="https://receiver.example.org/results",
        headers={},
        body=CONTENT,
        json_body=body,
        timeout=5,
        secret_header_names=frozenset(),
        secret_values=frozenset(),
    )
    payload = WebhookDeliveryPayload(
        run=SimpleNamespace(),  # type: ignore[arg-type]
        step=SimpleNamespace(),  # type: ignore[arg-type]
        step_result=SimpleNamespace(),  # type: ignore[arg-type]
        text_payload="",
        context={},
        audit_actor=None,
        run_result_body=body,
    )

    for text in (repr(request), repr(payload)):
        assert MARKER.decode() not in text
        assert body["content_base64"] not in text


# --- Text deliverables ------------------------------------------------------

TEXT = "# Möte\n\nBeslut: MARKER-text"


def _text_deliverable(step_id: UUID | None = None) -> FlowRunTextDeliverablePublic:
    return FlowRunTextDeliverablePublic(
        kind="text",
        step_id=step_id or uuid4(),
        step_order=2,
        label="Sammanfattning",
        output_type=FlowOutputType.TEXT,
        delivery="payload",
    )


def _step_result(
    deliverable: FlowRunTextDeliverablePublic,
    output_payload_json: dict[str, object] | None,
    *,
    attempt_no: int = 2,
) -> FlowStepResult:
    now = datetime(2026, 11, 20, 8, 4, tzinfo=timezone.utc)
    return FlowStepResult(
        flow_run_id=RUN.id,
        flow_id=RUN.flow_id,
        tenant_id=TENANT_ID,
        step_id=deliverable.step_id,
        step_order=deliverable.step_order,
        current_attempt_no=attempt_no,
        output_payload_json=output_payload_json,
        status=FlowStepResultStatus.COMPLETED,
        created_at=now,
        updated_at=now,
    )


TENANT_ID = UUID("00000000-0000-4000-8000-000000000003")


def _overflow(
    text: str, file_id: UUID, *, preview: str = "# Möte"
) -> dict[str, object]:
    return {
        "text": preview,
        "text_overflow": {
            "generated_file_ids": [str(file_id)],
            "inline_text_bytes": len(preview.encode()),
            "full_text_bytes": len(text.encode()),
        },
    }


def _text_file(
    deliverable: FlowRunTextDeliverablePublic,
    content: bytes = TEXT.encode(),
    **overrides: object,
) -> FlowRunStepResultFile:
    return _file(
        content,
        **{
            "flow_run_id": RUN.id,
            "flow_id": RUN.flow_id,
            "tenant_id": TENANT_ID,
            "step_id": deliverable.step_id,
            "step_order": deliverable.step_order,
            "attempt_no": 2,
            "source": "generated_output",
            "name": "sammanfattning.txt",
            "mimetype": "text/plain",
            "file_type": FileType.TEXT,
            **overrides,
        },
    )


def _body(parts, contents=None):
    return run_result_body(
        run=RUN,  # pyright: ignore[reportArgumentType]
        parts=parts,
        contents=contents or {},
    )


@pytest.mark.parametrize("text", [TEXT, ""])
def test_a_text_is_sent_whole_by_its_step_without_files(text: str) -> None:
    deliverable = _text_deliverable()
    part = run_result_text(
        deliverable,
        step_result=_step_result(deliverable, {"text": text}),
        result_files=[],
    )
    document = _deliverable(_file())

    body = _body([part, document], {document.files[0].file_id: CONTENT})

    assert body["deliverables"][0] == {  # type: ignore[index]
        "kind": "text",
        "step_id": str(deliverable.step_id),
        "step_order": 2,
        "label": "Sammanfattning",
        "output_type": "text",
        "text": text,
    }
    assert body["deliverables"][1]["kind"] == "artifact"  # type: ignore[index]
    assert "text" not in body  # type: ignore[operator]
    check_run_result([part, document])
    assert run_result_file_ids([part, document]) == [document.files[0].file_id]


def test_a_text_kept_in_a_file_is_read_whole_from_that_file() -> None:
    deliverable = _text_deliverable()
    file = _text_file(deliverable)
    part = run_result_text(
        deliverable,
        step_result=_step_result(deliverable, _overflow(TEXT, file.file_id)),
        result_files=[file],
    )

    body = _body([part], {file.file_id: TEXT.encode()})

    assert body["deliverables"][0]["text"] == TEXT  # type: ignore[index]
    assert run_result_file_ids([part]) == [file.file_id]


@pytest.mark.parametrize(
    "output_payload_json",
    [None, {}, {"text": None}, {"structured": {"a": 1}}],
    ids=["purged", "empty", "null", "no-text"],
)
def test_a_text_the_step_no_longer_holds_refuses_the_body(
    output_payload_json: dict[str, object] | None,
) -> None:
    deliverable = _text_deliverable()

    with pytest.raises(ValueError) as refused:
        run_result_text(
            deliverable,
            step_result=_step_result(deliverable, output_payload_json),
            result_files=[],
        )

    assert str(deliverable.step_id) in str(refused.value)


def test_a_text_of_a_step_without_a_result_refuses_the_body() -> None:
    deliverable = _text_deliverable()

    with pytest.raises(ValueError, match=str(deliverable.step_id)):
        run_result_text(deliverable, step_result=None, result_files=[])


@pytest.mark.parametrize(
    "overrides",
    [
        {"attempt_no": 1},
        {"step_id": uuid4()},
        {"flow_run_id": uuid4()},
        {"source": "declared_artifact"},
        {"size": len(TEXT.encode()) + 1},
        {"checksum": ""},
    ],
    ids=["old-attempt", "other-step", "other-run", "not-generated", "size", "checksum"],
)
def test_a_file_that_is_not_the_steps_own_text_refuses_the_body(
    overrides: dict[str, object],
) -> None:
    deliverable = _text_deliverable()
    file = _text_file(deliverable, **overrides)

    with pytest.raises(ValueError) as refused:
        run_result_text(
            deliverable,
            step_result=_step_result(deliverable, _overflow(TEXT, file.file_id)),
            result_files=[file],
        )

    assert MARKER.decode() not in str(refused.value)


def test_a_text_file_retention_removed_refuses_the_body() -> None:
    deliverable = _text_deliverable()
    file = _text_file(deliverable, availability="content_purged")

    with pytest.raises(ValueError, match="no longer stored"):
        run_result_text(
            deliverable,
            step_result=_step_result(deliverable, _overflow(TEXT, file.file_id)),
            result_files=[file],
        )


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        (None, "could not read"),
        (TEXT.encode() + b"x", "no longer matches"),
        (b"\xff" * len(TEXT.encode()), "no longer matches"),
    ],
    ids=["missing", "changed", "not-utf8-changed"],
)
def test_a_text_file_whose_bytes_are_wrong_refuses_the_body_beside_a_document(
    content: bytes | None, reason: str
) -> None:
    deliverable = _text_deliverable()
    file = _text_file(deliverable)
    part = run_result_text(
        deliverable,
        step_result=_step_result(deliverable, _overflow(TEXT, file.file_id)),
        result_files=[file],
    )
    document = _deliverable(_file())
    contents = {document.files[0].file_id: CONTENT}
    if content is not None:
        contents[file.file_id] = content

    with pytest.raises(ValueError, match=reason) as refused:
        _body([document, part], contents)

    assert "MARKER-text" not in str(refused.value)


def test_a_text_file_that_is_not_utf8_refuses_the_body() -> None:
    deliverable = _text_deliverable()
    invalid = b"\xff\xfe not text"
    file = _text_file(deliverable, invalid)
    part = run_result_text(
        deliverable,
        step_result=_step_result(
            deliverable, _overflow("x" * len(invalid), file.file_id, preview="x")
        ),
        result_files=[file],
    )

    with pytest.raises(ValueError, match="not UTF-8") as refused:
        _body([part], {file.file_id: invalid})

    assert str(file.file_id) in str(refused.value)


def test_text_and_files_together_are_held_to_the_cap_before_any_is_read() -> None:
    deliverable = _text_deliverable()
    inline = RunResultText(deliverable=deliverable, inline="é" * 10)
    exact = _deliverable(_file(size=RUN_RESULT_MAX_BYTES - 20))

    check_run_result([inline, exact])
    with pytest.raises(ValueError, match="more than"):
        check_run_result([inline, _deliverable(_file(size=RUN_RESULT_MAX_BYTES - 19))])

    file_text = RunResultText(
        deliverable=deliverable, file=_text_file(deliverable, size=RUN_RESULT_MAX_BYTES)
    )
    check_run_result([file_text])
    with pytest.raises(ValueError, match="more than"):
        check_run_result([file_text, _deliverable(_file(size=1))])
