"""Unit tests for the Help Assistant template registry.

The registry is the single code-owned source of installable Help Assistants.
Templates carry identity (name/description), the shipped instructions
(``prompt_text``) applied on install, and the fixed Help-Assistant invariants.
The Prompt Guide's prompt is what drives the ``eneo-question`` Q&A rendering on
assistant settings pages, so install (and re-install) must reproduce it.
"""

from __future__ import annotations

from typing import cast

import pytest

from eneo.help_assistants.domain.helper_kind import HelperKind
from eneo.help_assistants.templates import (
    PROMPT_GUIDE_TEMPLATE,
    TEMPLATES_BY_KIND,
    HelperAssistantTemplate,
    get_template,
    list_templates,
)


def test_prompt_guide_template_is_registered():
    template = get_template(HelperKind.PROMPT_GUIDE)

    assert template is PROMPT_GUIDE_TEMPLATE
    assert isinstance(template, HelperAssistantTemplate)
    assert TEMPLATES_BY_KIND[HelperKind.PROMPT_GUIDE] is template


def test_template_carries_identity_invariants_and_shipped_instructions():
    template = get_template(HelperKind.PROMPT_GUIDE)

    assert template.name == "Prompt Guide"
    assert template.description
    # Help assistants ship with logging/insights off.
    assert template.logging_enabled is False
    assert template.insight_enabled is False
    # Instructions ship with the template and drive the structured Q&A UI.
    assert template.prompt_text
    assert "eneo-question" in template.prompt_text


def test_list_templates_includes_prompt_guide():
    kinds = {kind for kind, _template in list_templates()}

    assert HelperKind.PROMPT_GUIDE in kinds


def test_get_template_raises_keyerror_for_unknown_kind():
    class _FakeKind:
        UNKNOWN = "unknown_kind"

    with pytest.raises(KeyError):
        get_template(cast(HelperKind, _FakeKind.UNKNOWN))
