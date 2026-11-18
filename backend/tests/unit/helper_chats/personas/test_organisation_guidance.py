"""The organisation's guidance comes after a helper chat's persona, under an
introduction that ranks it below the persona's rules, and is left out when
there is none."""

from __future__ import annotations

import pytest

from eneo.helper_chats.personas.assistant import ASSISTANT_INSTRUCTIONS
from eneo.helper_chats.personas.organisation_guidance import (
    ORGANISATION_GUIDANCE_INTRODUCTION,
    with_organisation_guidance,
)


@pytest.mark.parametrize("guidance", ["", "  \n\t "])
def test_without_guidance_the_persona_is_unchanged(guidance: str) -> None:
    assert with_organisation_guidance(ASSISTANT_INSTRUCTIONS, guidance) == (
        ASSISTANT_INSTRUCTIONS
    )


def test_the_guidance_follows_the_persona_under_its_introduction() -> None:
    guidance = "Tilltala alltid personen med du.\nAnge alltid källan."

    persona = with_organisation_guidance(ASSISTANT_INSTRUCTIONS, f"\n{guidance}  ")

    assert persona == (
        ASSISTANT_INSTRUCTIONS
        + "\n"
        + ORGANISATION_GUIDANCE_INTRODUCTION
        + "\n"
        + guidance
        + "\n"
    )
    assert persona.startswith(ASSISTANT_INSTRUCTIONS)
    assert persona.endswith(guidance + "\n")


def test_the_introduction_says_whose_it_is_and_what_it_cannot_change() -> None:
    introduction = " ".join(ORGANISATION_GUIDANCE_INTRODUCTION.split())

    assert introduction.startswith("Organisation guidance.")
    assert "An administrator of the person's organisation" in introduction
    assert "runs to the end of these instructions" in introduction
    assert "It cannot change what your tools may do" in introduction
    assert "it cannot set aside a rule above" in introduction
    assert "the rules above apply" in introduction
    assert chr(0x2014) not in introduction
    assert chr(0x2013) not in introduction
