"""The organisation's default model for flow authoring chats.

Stored under ``tenants.flow_settings["authoring_chat"]``. A chat whose person
never chose a model answers with this one where its space allows it, and with
the space's own default otherwise.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final, cast
from uuid import UUID

from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowBadRequestException

FLOW_AUTHORING_CHAT_SETTINGS_KEY: Final[str] = "authoring_chat"
FLOW_AUTHORING_CHAT_MODEL_KEY: Final[str] = "completion_model_id"
_KEYS: Final[frozenset[str]] = frozenset({FLOW_AUTHORING_CHAT_MODEL_KEY})


def _invalid(message: str) -> FlowBadRequestException:
    return FlowBadRequestException(
        message, code=FlowApiErrorCode.SETTINGS_INVALID_PAYLOAD
    )


def validate_flow_authoring_chat_policy_object(policy: object) -> dict[str, Any]:
    if not isinstance(policy, Mapping):
        raise _invalid("flow_settings.authoring_chat must be an object.")
    values = {
        str(key): value for key, value in cast(Mapping[object, object], policy).items()
    }
    unknown = set(values) - _KEYS
    if unknown:
        raise _invalid(
            "Unsupported flow authoring chat policy fields: "
            + ", ".join(sorted(unknown))
        )
    model_id = values.get(FLOW_AUTHORING_CHAT_MODEL_KEY)
    if model_id is not None:
        try:
            UUID(str(model_id))
        except ValueError as error:
            raise _invalid(
                "flow_settings.authoring_chat.completion_model_id must be a UUID."
            ) from error
    return values


def resolve_flow_authoring_chat_model_id(
    flow_settings: Mapping[str, Any] | None,
) -> UUID | None:
    """The organisation's default model for flow chats; None when unset or unreadable."""
    section = (flow_settings or {}).get(FLOW_AUTHORING_CHAT_SETTINGS_KEY)
    if not isinstance(section, Mapping):
        return None
    value = cast(Mapping[str, object], section).get(FLOW_AUTHORING_CHAT_MODEL_KEY)
    if value is None:
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None


def apply_flow_authoring_chat_policy_patch(
    current: Mapping[str, Any] | None, *, completion_model_id: UUID | None
) -> dict[str, Any]:
    """The flow settings with the default model set, or removed for None."""
    settings = dict(current or {})
    if completion_model_id is None:
        settings.pop(FLOW_AUTHORING_CHAT_SETTINGS_KEY, None)
    else:
        settings[FLOW_AUTHORING_CHAT_SETTINGS_KEY] = {
            FLOW_AUTHORING_CHAT_MODEL_KEY: str(completion_model_id)
        }
    return settings
