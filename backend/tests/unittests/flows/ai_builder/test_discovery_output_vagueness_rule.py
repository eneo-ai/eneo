"""Unit tests for the output-vagueness detector in the AI Builder discovery flow.

The detector `looks_like_output_is_vague` decides whether a user message should
block on the `final_output_mode` question. It fires whenever the flow carries a
structural signal that the output format matters (document/audio/case-like
input, or a text/docx default) OR the user mentions an output artifact
explicitly. For pure text-only descriptions with no artifact nouns, generic
creation verbs ("skapa", "create", "producera") alone should not fire it —
those describe the act of building the flow, not the artifact it delivers.
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


def test_skapa_on_plain_text_does_not_trigger_output_vagueness() -> None:
    profile = _profile_for("Jag vill skapa ett flöde som bearbetar min text för mig.")
    assert looks_like_output_is_vague(profile) is False


def test_create_on_plain_text_does_not_trigger_output_vagueness() -> None:
    profile = _profile_for(
        "I want to create a flow that processes my text for me.",
        ui_language="en",
    )
    assert looks_like_output_is_vague(profile) is False


def test_producera_on_plain_text_does_not_trigger_output_vagueness() -> None:
    profile = _profile_for("Jag vill producera något från min text.")
    assert looks_like_output_is_vague(profile) is False


def test_real_output_word_still_triggers_vagueness() -> None:
    profile = _profile_for(
        "Jag vill få ett resultat från mina kommunala dokument som jag kan använda."
    )
    assert looks_like_output_is_vague(profile) is True


def test_document_like_flow_without_output_keyword_triggers_vagueness() -> None:
    """A document-analysis description without explicit output nouns should fire.

    This is the class of case the detector used to miss: the user describes a
    flow that takes documents and does something with them, but never says the
    word "rapport"/"summary"/etc. The planner would then auto-pick a final
    output type instead of asking, producing surprising results for multi-step
    flows. The gate now fires on structural signals alone.
    """
    profile = _profile_for(
        "Jag vill bygga ett flöde som analyserar mina uppladdade dokument i "
        "flera steg och levererar något till handläggaren."
    )
    assert looks_like_output_is_vague(profile) is True


def test_case_like_flow_without_output_keyword_triggers_vagueness() -> None:
    """Case-like flows (ärende / case material) without output nouns also fire.

    Covers the IBIC-shaped conversation: the user describes a case-handling
    flow in Swedish without ever naming the output artifact, and the planner
    previously silently committed to JSON. The detector now asks instead.
    """
    profile = _profile_for(
        "Jag vill skapa ett ärendeflöde i flera steg som hjälper mig bedöma "
        "underlaget innan jag skickar vidare."
    )
    assert looks_like_output_is_vague(profile) is True
