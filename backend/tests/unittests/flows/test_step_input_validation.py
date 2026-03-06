from __future__ import annotations

import pytest

from intric.main.exceptions import TypedIOValidationException
from intric.flows.runtime.step_input_validation import (
    validate_input_contract,
    validate_runtime_input_policy,
)
from intric.flows.type_policies import INPUT_TYPE_POLICIES, InputTypePolicy


def test_validate_runtime_input_policy_rejects_unsupported_input_type() -> None:
    with pytest.raises(TypedIOValidationException) as exc:
        validate_runtime_input_policy(
            step_order=1,
            input_type="image",
            input_source="flow_input",
            raw_extracted_text="",
        )

    assert exc.value.code == "typed_io_unsupported_type"


def test_validate_runtime_input_policy_rejects_document_non_flow_input() -> None:
    with pytest.raises(TypedIOValidationException) as exc:
        validate_runtime_input_policy(
            step_order=2,
            input_type="document",
            input_source="previous_step",
            raw_extracted_text="hello",
        )

    assert exc.value.code == "typed_io_document_source_unsupported"


def test_validate_runtime_input_policy_rejects_file_non_flow_input() -> None:
    with pytest.raises(TypedIOValidationException) as exc:
        validate_runtime_input_policy(
            step_order=21,
            input_type="file",
            input_source="previous_step",
            raw_extracted_text="hello",
        )

    assert exc.value.code == "typed_io_file_source_unsupported"


def test_validate_runtime_input_policy_rejects_empty_extraction_when_required() -> None:
    with pytest.raises(TypedIOValidationException) as exc:
        validate_runtime_input_policy(
            step_order=3,
            input_type="file",
            input_source="flow_input",
            raw_extracted_text="   ",
        )

    assert exc.value.code == "typed_io_empty_extraction"


def test_validate_runtime_input_policy_rejects_missing_image_files(monkeypatch) -> None:
    monkeypatch.setitem(
        INPUT_TYPE_POLICIES,
        "image",
        InputTypePolicy(
            channel="files_only",
            contract_allowed=False,
            requires_extraction=False,
            requires_files=True,
            supported=True,
        ),
    )

    with pytest.raises(TypedIOValidationException) as exc:
        validate_runtime_input_policy(
            step_order=31,
            input_type="image",
            input_source="flow_input",
            raw_extracted_text="image prompt",
            files=[],
        )

    assert exc.value.code == "typed_io_missing_required_files"


def test_validate_runtime_input_policy_rejects_non_image_files_for_image_input(monkeypatch) -> None:
    monkeypatch.setitem(
        INPUT_TYPE_POLICIES,
        "image",
        InputTypePolicy(
            channel="files_only",
            contract_allowed=False,
            requires_extraction=False,
            requires_files=True,
            supported=True,
        ),
    )

    files = [
        type("FileStub", (), {"name": "note.txt", "mimetype": "text/plain"})(),
    ]

    with pytest.raises(TypedIOValidationException) as exc:
        validate_runtime_input_policy(
            step_order=32,
            input_type="image",
            input_source="flow_input",
            raw_extracted_text="image prompt",
            files=files,
        )

    assert exc.value.code == "typed_io_missing_required_files"


def test_validate_runtime_input_policy_rejects_mixed_image_and_non_image_files(monkeypatch) -> None:
    monkeypatch.setitem(
        INPUT_TYPE_POLICIES,
        "image",
        InputTypePolicy(
            channel="files_only",
            contract_allowed=False,
            requires_extraction=False,
            requires_files=True,
            supported=True,
        ),
    )

    files = [
        type("FileStub", (), {"name": "pic.png", "mimetype": "image/png"})(),
        type("FileStub", (), {"name": "note.txt", "mimetype": "text/plain"})(),
    ]

    with pytest.raises(TypedIOValidationException) as exc:
        validate_runtime_input_policy(
            step_order=33,
            input_type="image",
            input_source="flow_input",
            raw_extracted_text="image prompt",
            files=files,
        )

    assert exc.value.code == "typed_io_invalid_file_type"


def test_validate_input_contract_returns_json_contract_metadata() -> None:
    contract_validation = validate_input_contract(
        step_order=4,
        input_type="json",
        input_contract={"type": "object", "properties": {"name": {"type": "string"}}},
        text='{"name":"A"}',
        structured={"name": "A"},
    )

    assert contract_validation == {
        "schema_type_hint": "object",
        "parse_attempted": False,
        "parse_succeeded": True,
        "candidate_type": "dict",
    }


def test_validate_input_contract_rejects_json_without_structured_input() -> None:
    with pytest.raises(TypedIOValidationException) as exc:
        validate_input_contract(
            step_order=5,
            input_type="json",
            input_contract={"type": "object"},
            text='{"name":"A"}',
            structured=None,
        )

    assert exc.value.code == "typed_io_invalid_json_input"


def test_validate_input_contract_parses_text_for_structured_schema() -> None:
    contract_validation = validate_input_contract(
        step_order=6,
        input_type="text",
        input_contract={"type": "object", "properties": {"a": {"type": "number"}}},
        text='{"a":1}',
        structured=None,
    )

    assert contract_validation == {
        "schema_type_hint": "object",
        "parse_attempted": True,
        "parse_succeeded": True,
        "candidate_type": "dict",
    }


def test_validate_input_contract_keeps_text_for_string_schema() -> None:
    contract_validation = validate_input_contract(
        step_order=7,
        input_type="text",
        input_contract={"type": "string"},
        text="hello",
        structured=None,
    )

    assert contract_validation == {
        "schema_type_hint": "string",
        "parse_attempted": False,
        "parse_succeeded": False,
        "candidate_type": "str",
    }


def test_validate_input_contract_invalid_text_json_attaches_parse_metadata() -> None:
    with pytest.raises(TypedIOValidationException) as exc:
        validate_input_contract(
            step_order=41,
            input_type="text",
            input_contract={"type": "object", "properties": {"a": {"type": "number"}}},
            text="{invalid-json",
            structured=None,
        )

    assert exc.value.code == "typed_io_contract_violation"
    contract_validation = getattr(exc.value, "contract_validation", None)
    assert contract_validation is not None
    assert contract_validation["parse_attempted"] is True
    assert contract_validation["parse_succeeded"] is False
    assert contract_validation["candidate_type"] == "str"
