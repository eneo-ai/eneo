"""The organisation's settings for the helper chat on assistants.

Stored under ``tenants.flow_settings["helper_chat"]``, beside the flow chat's
section (``"authoring_chat"``) whose default model every helper chat shares.
Every key is optional and an absent one has its default, so a tenant that
never set anything has the chat on and no guidance:

- ``enabled``: whether people may open and continue a helper chat on an
  assistant. The flow chat does not follow it.
- ``guidance``: the organisation's own rules for the helper, added to the
  persona after its base rules.
- ``seeded_completion_model_id``: the default model that the one-time seed
  from the prompt guide set, kept so that the seed can be undone. The API
  neither shows nor takes it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, cast
from uuid import UUID

HELPER_CHAT_SETTINGS_KEY: Final[str] = "helper_chat"
HELPER_CHAT_ENABLED_KEY: Final[str] = "enabled"
HELPER_CHAT_GUIDANCE_KEY: Final[str] = "guidance"
HELPER_CHAT_SEEDED_MODEL_KEY: Final[str] = "seeded_completion_model_id"
_KEYS: Final[frozenset[str]] = frozenset(
    {HELPER_CHAT_ENABLED_KEY, HELPER_CHAT_GUIDANCE_KEY, HELPER_CHAT_SEEDED_MODEL_KEY}
)

# The guidance reaches the model on every turn of every helper chat in the
# organisation, so it stays a few paragraphs long.
HELPER_CHAT_GUIDANCE_MAX_LENGTH: Final[int] = 4000


class HelperChatPolicyErrorCode(StrEnum):
    """The codes of the settings endpoint's refusals."""

    INVALID_PAYLOAD = "helper_chat_policy_invalid_payload"
    MODEL_UNAVAILABLE = "helper_chat_policy_model_unavailable"
    MODEL_WITHOUT_TOOLS = "helper_chat_policy_model_without_tools"


@dataclass(frozen=True)
class HelperChatPolicy:
    enabled: bool = True
    guidance: str = ""


def normalize_guidance(guidance: str) -> str:
    """The guidance as it is kept: without surrounding whitespace. Refused
    (``ValueError``) over the length cap or with a NUL character, which the
    database cannot store."""
    text = guidance.strip()
    if len(text) > HELPER_CHAT_GUIDANCE_MAX_LENGTH:
        raise ValueError(
            "The helper chat's guidance is longer than "
            f"{HELPER_CHAT_GUIDANCE_MAX_LENGTH} characters."
        )
    if "\x00" in text:
        raise ValueError("The helper chat's guidance holds a NUL character.")
    return text


def validate_helper_chat_policy_object(policy: object) -> dict[str, Any]:
    """The stored section, checked key by key; ``ValueError`` names what is
    wrong."""
    if not isinstance(policy, Mapping):
        raise ValueError("flow_settings.helper_chat must be an object.")
    values = {
        str(key): value for key, value in cast(Mapping[object, object], policy).items()
    }
    unknown = set(values) - _KEYS
    if unknown:
        raise ValueError(
            "Unsupported helper chat policy fields: " + ", ".join(sorted(unknown))
        )
    if HELPER_CHAT_ENABLED_KEY in values and not isinstance(
        values[HELPER_CHAT_ENABLED_KEY], bool
    ):
        raise ValueError("flow_settings.helper_chat.enabled must be true or false.")
    if HELPER_CHAT_GUIDANCE_KEY in values:
        guidance = values[HELPER_CHAT_GUIDANCE_KEY]
        if not isinstance(guidance, str):
            raise ValueError("flow_settings.helper_chat.guidance must be a string.")
        if normalize_guidance(guidance) != guidance:
            raise ValueError(
                "flow_settings.helper_chat.guidance must not start or end with "
                "whitespace."
            )
    if HELPER_CHAT_SEEDED_MODEL_KEY in values:
        try:
            UUID(str(values[HELPER_CHAT_SEEDED_MODEL_KEY]))
        except ValueError as error:
            raise ValueError(
                "flow_settings.helper_chat.seeded_completion_model_id must be a UUID."
            ) from error
    return values


def _section(flow_settings: Mapping[str, Any] | None) -> Mapping[str, object]:
    section = (flow_settings or {}).get(HELPER_CHAT_SETTINGS_KEY)
    if not isinstance(section, Mapping):
        return {}
    return cast(Mapping[str, object], section)


def resolve_helper_chat_policy(
    flow_settings: Mapping[str, Any] | None,
) -> HelperChatPolicy:
    """The policy in force; a key that is absent or unreadable has its
    default."""
    section = _section(flow_settings)
    enabled = section.get(HELPER_CHAT_ENABLED_KEY)
    guidance = section.get(HELPER_CHAT_GUIDANCE_KEY)
    return HelperChatPolicy(
        enabled=enabled if isinstance(enabled, bool) else True,
        guidance=guidance.strip() if isinstance(guidance, str) else "",
    )


def apply_helper_chat_policy_patch(
    current: Mapping[str, Any] | None,
    *,
    enabled: bool | None = None,
    guidance: str | None = None,
    default_model_set: bool = False,
) -> dict[str, Any]:
    """The flow settings with the helper chat's section changed: ``enabled``
    and ``guidance`` are set where given and kept where None. A default
    model the administrator sets is their own, so the seed's record of the
    model it set is dropped."""
    settings = dict(current or {})
    section = dict(_section(settings))
    if enabled is not None:
        section[HELPER_CHAT_ENABLED_KEY] = enabled
    if guidance is not None:
        section[HELPER_CHAT_GUIDANCE_KEY] = normalize_guidance(guidance)
    if default_model_set:
        section.pop(HELPER_CHAT_SEEDED_MODEL_KEY, None)
    if section:
        settings[HELPER_CHAT_SETTINGS_KEY] = validate_helper_chat_policy_object(section)
    else:
        settings.pop(HELPER_CHAT_SETTINGS_KEY, None)
    return settings
