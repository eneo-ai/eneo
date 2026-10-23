from uuid import uuid4

import pytest

from eneo.flows.domain.flow_authoring_chat_policy import (
    apply_flow_authoring_chat_policy_patch,
    resolve_flow_authoring_chat_model_id,
    validate_flow_authoring_chat_policy_object,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowBadRequestException
from eneo.flows.flow_settings import (
    normalize_flow_settings_object,
    validate_flow_settings_write,
)


def test_a_set_default_is_read_back_and_other_settings_are_kept() -> None:
    model_id = uuid4()
    current = {"runtime_policy": {"version": 1, "max_concurrent_runs": 2}}

    saved = apply_flow_authoring_chat_policy_patch(
        current, completion_model_id=model_id
    )

    assert resolve_flow_authoring_chat_model_id(saved) == model_id
    assert saved["runtime_policy"] == current["runtime_policy"]
    assert normalize_flow_settings_object(saved) == saved


def test_null_removes_the_default() -> None:
    saved = apply_flow_authoring_chat_policy_patch(
        {"authoring_chat": {"completion_model_id": str(uuid4())}},
        completion_model_id=None,
    )

    assert "authoring_chat" not in saved
    assert resolve_flow_authoring_chat_model_id(saved) is None


@pytest.mark.parametrize(
    "stored",
    [
        None,
        {},
        {"authoring_chat": "x"},
        {"authoring_chat": {"completion_model_id": "x"}},
    ],
)
def test_an_unset_or_unreadable_default_follows_the_space(stored) -> None:
    assert resolve_flow_authoring_chat_model_id(stored) is None


@pytest.mark.parametrize(
    "section",
    [
        "a model",
        {"completion_model_id": "not-a-uuid"},
        {"completion_model_id": str(uuid4()), "reasoning_effort": "high"},
    ],
)
def test_a_malformed_section_is_refused_on_write(section) -> None:
    with pytest.raises(FlowBadRequestException) as refused:
        validate_flow_settings_write({"authoring_chat": section})

    assert refused.value.code is FlowApiErrorCode.SETTINGS_INVALID_PAYLOAD


def test_a_valid_section_passes() -> None:
    section = {"completion_model_id": str(uuid4())}

    assert validate_flow_authoring_chat_policy_object(section) == section
    assert validate_flow_settings_write({"authoring_chat": section}) == {
        "authoring_chat": section
    }
