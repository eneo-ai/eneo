from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from eneo.flows.assistant_execution_snapshot import (
    assistant_execution_surface_hash,
    build_assistant_execution_snapshot,
    validate_assistant_execution_snapshot,
)
from eneo.main.exceptions import BadRequestException


def _assistant(
    *,
    prompt: str = "Answer carefully.",
    model_name: str = "gpt-5.4-nano",
    knowledge_name: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        origin="flow_managed",
        prompt=SimpleNamespace(text=prompt),
        completion_model=SimpleNamespace(
            id=uuid4(),
            name=model_name,
            nickname="Nano",
            litellm_model_name="openai/gpt-5.4-nano",
        ),
        completion_model_kwargs={"temperature": 0.2},
        collections=[]
        if knowledge_name is None
        else [
            SimpleNamespace(
                id="collection-1",
                name=knowledge_name,
            )
        ],
        websites=[],
        integration_knowledge_list=[],
    )


def _execution_hash(assistant: SimpleNamespace):
    snapshot = build_assistant_execution_snapshot(assistant=assistant)
    assert snapshot is not None
    return snapshot["execution_surface_hash"]


def _snapshot() -> tuple[dict[str, object], SimpleNamespace]:
    assistant = _assistant()
    snapshot = build_assistant_execution_snapshot(assistant=assistant)
    assert snapshot is not None
    return snapshot, assistant


def test_assistant_execution_hash_changes_when_prompt_changes():
    first = _assistant(prompt="Summarize the case.")
    second = _assistant(prompt="Summarize the case and cite uncertainties.")
    second.id = first.id
    second.completion_model.id = first.completion_model.id

    assert _execution_hash(first) != _execution_hash(second)


def test_assistant_execution_hash_ignores_model_and_knowledge_display_names():
    first = _assistant(model_name="GPT Nano", knowledge_name="Old label")
    second = _assistant(model_name="GPT Nano renamed", knowledge_name="New label")
    second.id = first.id
    second.completion_model.id = first.completion_model.id

    assert _execution_hash(first) == _execution_hash(second)


def test_assistant_execution_hash_ignores_none_model_kwargs():
    first = _assistant()
    second = _assistant()
    second.id = first.id
    second.completion_model.id = first.completion_model.id
    first.completion_model_kwargs = {"temperature": 0.2, "top_p": None}
    second.completion_model_kwargs = {"temperature": 0.2}

    assert _execution_hash(first) == _execution_hash(second)


def test_validate_assistant_execution_snapshot_accepts_builder_output() -> None:
    snapshot, assistant = _snapshot()

    validated = validate_assistant_execution_snapshot(
        snapshot=snapshot,
        assistant_id=assistant.id,
    )

    assert validated == snapshot


@pytest.mark.parametrize(
    "missing_field",
    [
        "schema_version",
        "assistant_id",
        "origin",
        "instructions",
        "completion_model",
        "completion_model_kwargs",
        "knowledge_refs",
        "execution_surface_hash",
    ],
)
def test_validate_assistant_execution_snapshot_requires_exact_fields(
    missing_field: str,
) -> None:
    snapshot, assistant = _snapshot()
    snapshot.pop(missing_field)

    with pytest.raises(BadRequestException, match="required fields"):
        validate_assistant_execution_snapshot(
            snapshot=snapshot,
            assistant_id=assistant.id,
        )


def test_validate_assistant_execution_snapshot_rejects_unknown_fields() -> None:
    snapshot, assistant = _snapshot()
    snapshot["future_execution_setting"] = True

    with pytest.raises(BadRequestException, match="unsupported fields"):
        validate_assistant_execution_snapshot(
            snapshot=snapshot,
            assistant_id=assistant.id,
        )


def test_validate_assistant_execution_snapshot_rejects_unsupported_schema() -> None:
    snapshot, assistant = _snapshot()
    snapshot["schema_version"] = 3

    with pytest.raises(BadRequestException, match="schema_version"):
        validate_assistant_execution_snapshot(
            snapshot=snapshot,
            assistant_id=assistant.id,
        )


def test_validate_assistant_execution_snapshot_rejects_assistant_mismatch() -> None:
    snapshot, _ = _snapshot()

    with pytest.raises(BadRequestException, match="assistant_id"):
        validate_assistant_execution_snapshot(
            snapshot=snapshot,
            assistant_id=uuid4(),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("origin", ["flow_managed"]),
        ("instructions", {"text": "Answer carefully."}),
        ("completion_model", []),
        ("completion_model_kwargs", {"nested": [object()]}),
        ("knowledge_refs", [{"kind": "collection", "id": 7, "name": None}]),
    ],
)
def test_validate_assistant_execution_snapshot_rejects_invalid_nested_shape(
    field: str,
    value: object,
) -> None:
    snapshot, assistant = _snapshot()
    snapshot[field] = value

    with pytest.raises(BadRequestException, match=field):
        validate_assistant_execution_snapshot(
            snapshot=snapshot,
            assistant_id=assistant.id,
        )


@pytest.mark.parametrize(
    "stored_hash",
    [
        "abc",
        "A" * 64,
        "g" * 64,
    ],
)
def test_validate_assistant_execution_snapshot_rejects_invalid_hash_format(
    stored_hash: str,
) -> None:
    snapshot, assistant = _snapshot()
    snapshot["execution_surface_hash"] = stored_hash

    with pytest.raises(BadRequestException, match="lowercase SHA-256"):
        validate_assistant_execution_snapshot(
            snapshot=snapshot,
            assistant_id=assistant.id,
        )


def test_validate_assistant_execution_snapshot_rejects_stale_hash() -> None:
    snapshot, assistant = _snapshot()
    original_hash = snapshot["execution_surface_hash"]
    snapshot["instructions"] = "Altered after publication."

    assert original_hash != assistant_execution_surface_hash(snapshot)
    with pytest.raises(BadRequestException, match="does not match its payload"):
        validate_assistant_execution_snapshot(
            snapshot=snapshot,
            assistant_id=assistant.id,
        )


def test_v1_fixed_historical_hash_and_writer_are_unchanged():
    assistant_id = UUID("00000000-0000-0000-0000-000000000001")
    snapshot = {
        "schema_version": 1,
        "assistant_id": str(assistant_id),
        "origin": "flow_managed",
        "instructions": "Frozen instructions",
        "completion_model": {
            "id": "00000000-0000-0000-0000-000000000002",
            "name": "model-a",
            "nickname": "Model label",
            "litellm_model_name": None,
        },
        "completion_model_kwargs": {"temperature": 0.2},
        "knowledge_refs": [],
        "execution_surface_hash": "9bafa9cede765e142c9c991fd8d48c22316dea4b06208786269634eeb07e8433",
    }
    assert (
        validate_assistant_execution_snapshot(
            snapshot=snapshot, assistant_id=assistant_id
        )
        == snapshot
    )
    assert (
        assistant_execution_surface_hash(snapshot) == snapshot["execution_surface_hash"]
    )
    written = build_assistant_execution_snapshot(assistant=_assistant())
    assert written["schema_version"] == 1


def _v2_snapshot_payload():
    payload = {
        "schema_version": 2,
        "assistant_id": "00000000-0000-0000-0000-000000000001",
        "origin": "flow_managed",
        "instructions": "Frozen instructions",
        "completion_model": {
            "model_id": "00000000-0000-0000-0000-000000000002",
            "provider_id": "00000000-0000-0000-0000-000000000003",
            "provider_type": "provider-a",
            "resolved_route": "provider-a/model-a",
        },
        "completion_model_kwargs": {"temperature": 0.2},
        "knowledge_refs": [],
        "attachments": [],
        "inline_file_text": False,
    }
    return {
        **payload,
        "execution_surface_hash": assistant_execution_surface_hash(payload),
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", 3),
        ("schema_version", True),
        ("inline_file_text", "false"),
        ("completion_model_kwargs", {"unknown": 1}),
        ("completion_model_kwargs", {"temperature": "0.2"}),
        ("completion_model_kwargs", {"response_format": {"value": float("nan")}}),
        ("completion_model", {"model_id": "invalid"}),
        ("knowledge_refs", [{"kind": "unknown", "id": str(uuid4())}]),
        ("attachments", [{"file_id": str(uuid4()), "checksum": ""}]),
        ("execution_surface_hash", "a" * 64),
    ],
)
def test_v2_rejects_malformed_snapshot(field, value):
    snapshot = _v2_snapshot_payload()
    snapshot[field] = value
    with pytest.raises(BadRequestException):
        validate_assistant_execution_snapshot(
            snapshot=snapshot, assistant_id=UUID(snapshot["assistant_id"])
        )


@pytest.mark.parametrize(
    "field", ["inline_file_text", "attachments", "completion_model", "origin"]
)
def test_v2_requires_frozen_fields(field):
    snapshot = _v2_snapshot_payload()
    del snapshot[field]
    with pytest.raises(BadRequestException):
        validate_assistant_execution_snapshot(
            snapshot=snapshot, assistant_id=UUID(snapshot["assistant_id"])
        )


def test_v2_canonicalizes_knowledge_but_preserves_attachment_order():
    snapshot = _v2_snapshot_payload()
    first_id, second_id = str(UUID(int=10)), str(UUID(int=20))
    snapshot["knowledge_refs"] = [
        {"kind": "website", "id": second_id},
        {"kind": "collection", "id": first_id},
    ]
    snapshot["attachments"] = [
        {"file_id": second_id, "checksum": "second"},
        {"file_id": first_id, "checksum": "first"},
    ]
    snapshot["execution_surface_hash"] = assistant_execution_surface_hash(snapshot)
    validated = validate_assistant_execution_snapshot(
        snapshot=snapshot, assistant_id=UUID(snapshot["assistant_id"])
    )
    assert validated["knowledge_refs"][0] == {"kind": "collection", "id": first_id}
    assert validated["attachments"] == snapshot["attachments"]
    snapshot["attachments"].reverse()
    assert (
        assistant_execution_surface_hash(snapshot)
        != validated["execution_surface_hash"]
    )


def test_v2_rejects_unknown_field():
    snapshot = _v2_snapshot_payload()
    snapshot["future_setting"] = True
    with pytest.raises(BadRequestException):
        validate_assistant_execution_snapshot(
            snapshot=snapshot, assistant_id=UUID(snapshot["assistant_id"])
        )
