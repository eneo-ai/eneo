"""The helper chat's organisation settings: what is stored, what a read makes
of a missing or unreadable section, and what a write refuses."""

from __future__ import annotations

from uuid import uuid4

import pytest

from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowBadRequestException
from eneo.flows.flow_settings import (
    normalize_flow_settings_object,
    validate_flow_settings_write,
)
from eneo.helper_chats.policy import (
    HELPER_CHAT_GUIDANCE_MAX_LENGTH,
    HelperChatPolicy,
    apply_helper_chat_policy_patch,
    resolve_helper_chat_policy,
    validate_helper_chat_policy_object,
)

_RUNTIME = {"runtime_policy": {"version": 1, "max_concurrent_runs": 2}}


@pytest.mark.parametrize(
    "flow_settings",
    [
        None,
        {},
        _RUNTIME,
        {"helper_chat": "på"},
        {"helper_chat": {}},
        {"helper_chat": {"enabled": "no", "guidance": 7}},
    ],
)
def test_a_missing_or_unreadable_setting_has_its_default(flow_settings) -> None:
    assert resolve_helper_chat_policy(flow_settings) == HelperChatPolicy(
        enabled=True, guidance=""
    )


def test_what_is_saved_is_read_back_and_other_settings_are_kept() -> None:
    saved = apply_helper_chat_policy_patch(
        _RUNTIME, enabled=False, guidance="  Tilltala alltid personen med du.\n"
    )

    assert resolve_helper_chat_policy(saved) == HelperChatPolicy(
        enabled=False, guidance="Tilltala alltid personen med du."
    )
    assert saved["runtime_policy"] == _RUNTIME["runtime_policy"]
    assert normalize_flow_settings_object(saved) == saved
    assert validate_flow_settings_write(saved) == saved


def test_a_field_left_out_keeps_its_value() -> None:
    current = {"helper_chat": {"enabled": False, "guidance": "Ange källan."}}

    assert resolve_helper_chat_policy(
        apply_helper_chat_policy_patch(current, guidance="")
    ) == HelperChatPolicy(enabled=False, guidance="")
    assert resolve_helper_chat_policy(
        apply_helper_chat_policy_patch(current, enabled=True)
    ) == HelperChatPolicy(enabled=True, guidance="Ange källan.")


def test_the_seeds_default_model_is_forgotten_once_an_administrator_sets_one() -> None:
    seeded = {
        "authoring_chat": {"completion_model_id": str(uuid4())},
        "helper_chat": {"seeded_completion_model_id": str(uuid4())},
    }

    kept = apply_helper_chat_policy_patch(seeded, enabled=False)
    set_by_admin = apply_helper_chat_policy_patch(seeded, default_model_set=True)

    assert kept["helper_chat"] == {
        **seeded["helper_chat"],
        "enabled": False,
    }
    assert "helper_chat" not in set_by_admin
    assert set_by_admin["authoring_chat"] == seeded["authoring_chat"]


def test_the_guidance_is_capped() -> None:
    longest = "x" * HELPER_CHAT_GUIDANCE_MAX_LENGTH

    assert (
        resolve_helper_chat_policy(
            apply_helper_chat_policy_patch(None, guidance=f" {longest} ")
        ).guidance
        == longest
    )
    with pytest.raises(ValueError, match="longer than 4000"):
        apply_helper_chat_policy_patch(None, guidance=longest + "x")


@pytest.mark.parametrize(
    ("section", "message"),
    [
        ("på", "must be an object"),
        ({"enabled": "false"}, "enabled must be true or false"),
        ({"enabled": 0}, "enabled must be true or false"),
        ({"guidance": ["du"]}, "guidance must be a string"),
        ({"guidance": "x" * (HELPER_CHAT_GUIDANCE_MAX_LENGTH + 1)}, "longer than"),
        ({"guidance": "Ange\x00källan."}, "NUL"),
        ({"guidance": " Ange källan."}, "whitespace"),
        ({"seeded_completion_model_id": "modell"}, "must be a UUID"),
        ({"prompt": "Du är en guide."}, "Unsupported helper chat policy fields"),
    ],
)
def test_a_section_that_is_not_the_policy_is_refused(section, message) -> None:
    with pytest.raises(ValueError, match=message):
        validate_helper_chat_policy_object(section)


def test_a_write_of_the_flow_settings_refuses_an_invalid_section() -> None:
    with pytest.raises(FlowBadRequestException) as refused:
        validate_flow_settings_write(
            {**_RUNTIME, "helper_chat": {"guidance": "x" * 4001}}
        )

    assert refused.value.code == FlowApiErrorCode.SETTINGS_INVALID_PAYLOAD
