from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

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
    snapshot["schema_version"] = 2

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
