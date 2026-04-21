"""Unit tests for the output-vagueness detector in the AI Builder discovery flow.

The detector `looks_like_output_is_vague` decides whether a user message should
block on the `final_output_mode` question. It keys off a list of trigger words
that describe an output artifact. Generic creation verbs like "skapa",
"create", and "producera" describe the act of building the flow itself, not an
output artifact, so they should not cause the detector to fire on their own.
When a real output-intent word ("resultat", "rapport", …) is present the
detector should still fire.
"""

from __future__ import annotations

from intric.flows.ai_builder.ai_builder_discovery_issue_rules import (
    looks_like_output_is_vague,
)
from intric.flows.ai_builder.ai_builder_discovery_profile_builder import (
    build_discovery_profile,
)
from intric.flows.ai_builder.ai_builder_models import ConversationMessage


def _profile_for(text: str, ui_language: str = "sv"):
    return build_discovery_profile(
        [
            ConversationMessage(
                role="user",
                content=text,
                metadata={"ui_language": ui_language},
            )
        ],
        flow=None,
    )


def test_skapa_alone_does_not_trigger_output_vagueness() -> None:
    profile = _profile_for(
        "Jag vill skapa ett flöde som analyserar mina kommunala dokument för mig."
    )
    assert looks_like_output_is_vague(profile) is False


def test_create_alone_does_not_trigger_output_vagueness() -> None:
    profile = _profile_for(
        "I want to create a flow that analyzes my municipal documents for me.",
        ui_language="en",
    )
    assert looks_like_output_is_vague(profile) is False


def test_producera_alone_does_not_trigger_output_vagueness() -> None:
    profile = _profile_for(
        "Jag vill producera något från mina kommunala dokument som hjälper mig."
    )
    assert looks_like_output_is_vague(profile) is False


def test_real_output_word_still_triggers_vagueness() -> None:
    profile = _profile_for(
        "Jag vill få ett resultat från mina kommunala dokument som jag kan använda."
    )
    assert looks_like_output_is_vague(profile) is True
