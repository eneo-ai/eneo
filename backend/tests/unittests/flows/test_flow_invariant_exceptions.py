from __future__ import annotations

from dataclasses import is_dataclass
from uuid import uuid4

from eneo.flows.domain.flow_invariant_exceptions import (
    FlowInvariantError,
    FlowPersistedIdMissingError,
    FlowPublishedDefinitionInvalidError,
)
from eneo.flows.domain.runtime_invariant_exceptions import FlowRuntimeInvariantError
from eneo.main.exceptions import BadRequestException


def test_persisted_flow_id_missing_error_is_non_runtime_flow_invariant() -> None:
    assert issubclass(FlowPersistedIdMissingError, FlowInvariantError)
    assert not issubclass(FlowPersistedIdMissingError, FlowRuntimeInvariantError)


def test_persisted_flow_id_missing_error_is_frozen_slots_dataclass() -> None:
    exc = FlowPersistedIdMissingError()

    assert is_dataclass(exc)
    assert hasattr(exc, "__slots__")


def test_invalid_published_definition_error_is_non_runtime_flow_invariant() -> None:
    assert issubclass(FlowPublishedDefinitionInvalidError, FlowInvariantError)
    assert not issubclass(
        FlowPublishedDefinitionInvalidError, FlowRuntimeInvariantError
    )
    assert not issubclass(FlowPublishedDefinitionInvalidError, BadRequestException)


def test_invalid_published_definition_error_carries_parser_context() -> None:
    flow_id = uuid4()

    exc = FlowPublishedDefinitionInvalidError(
        flow_id=flow_id,
        flow_version=3,
        parser_message="Flow version step 1 is missing stable step identifiers.",
        parser_code="flow_version_missing_step_identifiers",
        parser_context={"step_order": 1},
    )

    assert is_dataclass(exc)
    assert hasattr(exc, "__slots__")
    assert exc.flow_id == flow_id
    assert exc.flow_version == 3
    assert exc.parser_code == "flow_version_missing_step_identifiers"
    assert exc.parser_context == {"step_order": 1}
    assert "flow_version_missing_step_identifiers" in str(exc)
    assert "missing stable step identifiers" in str(exc)
