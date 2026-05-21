from enum import Enum
from typing import cast

import pytest

from intric.help_assistants.defaults import (
    DEFAULTS_BY_KIND,
    PROMPT_GUIDE_DEFAULTS,
    HelperAssistantDefaults,
    HelperKind,
    get_defaults,
)


def test_get_defaults_returns_registered_prompt_guide_defaults():
    result = get_defaults(HelperKind.PROMPT_GUIDE)

    assert result is PROMPT_GUIDE_DEFAULTS
    assert isinstance(result, HelperAssistantDefaults)
    assert result.name == "Prompt Guide"
    assert result.logging_enabled is False
    assert result.insight_enabled is False
    assert result.data_retention_days == 30
    assert DEFAULTS_BY_KIND[HelperKind.PROMPT_GUIDE] is result


def test_get_defaults_raises_keyerror_for_unknown_kind():
    class _FakeKind(str, Enum):
        UNKNOWN = "unknown"

        def __str__(self) -> str:
            return self.value

    with pytest.raises(KeyError):
        get_defaults(cast(HelperKind, _FakeKind.UNKNOWN))


def test_prompt_guide_prompt_includes_ui_language_instruction():
    prompt = PROMPT_GUIDE_DEFAULTS.prompt_text

    assert "Swedish" in prompt
    assert "English" in prompt
