import json
from pathlib import Path
from uuid import UUID

import pytest

from eneo.main.exceptions import BadRequestException
from eneo.skills.domain.instruction_references import (
    FunctionInstructionReference,
    McpServerInstructionReference,
    McpToolInstructionReference,
    SkillInstructionReference,
    parse_instruction_references,
    render_instruction_references,
)

SKILL = UUID("11111111-1111-4111-8111-111111111111")
REVISION = UUID("22222222-2222-4222-8222-222222222222")
SERVER = UUID("33333333-3333-4333-8333-333333333333")
LINK = f"[Klartext](eneo-skill:{SKILL}@{REVISION})"


@pytest.mark.parametrize(
    "fixture",
    json.loads(
        (
            Path(__file__).resolve().parents[4]
            / "frontend/packages/skill-instructions/fixtures.json"
        ).read_text()
    ),
    ids=lambda fixture: fixture["name"],
)
def test_shared_browser_text_contract(fixture):
    if fixture.get("error"):
        with pytest.raises(BadRequestException):
            parse_instruction_references(fixture["text"])
        return
    references = parse_instruction_references(fixture["text"])
    assert [item.target.model_dump(mode="json") for item in references] == fixture[
        "targets"
    ]
    assert all(
        fixture["text"][item.start : item.end] == item.text for item in references
    )


def test_typed_references_keep_exact_identity_and_unicode_text():
    text = (
        f"Skriv ✨ med {LINK}.\n"
        f"Hämta [Aktuellt datum](eneo-mcp:{SERVER}), "
        f"[Sök](eneo-function:web_search) och "
        f"[Beräkna](eneo-tool:{SERVER}/r%C3%A4kna%2Fprocent%2520)."
    )
    references = parse_instruction_references(text)
    assert [ref.target for ref in references] == [
        SkillInstructionReference(skill_id=SKILL, revision_id=REVISION),
        McpServerInstructionReference(server_id=SERVER),
        FunctionInstructionReference(purpose="web_search"),
        McpToolInstructionReference(server_id=SERVER, tool_name="räkna/procent%20"),
    ]
    assert all(text[ref.start : ref.end] == ref.text for ref in references)
    assert render_instruction_references(text) == (
        f"Skriv ✨ med [Klartext] (Skill {SKILL}, revision {REVISION}).\n"
        f"Hämta [Aktuellt datum] (MCP {SERVER}; unavailable for this turn), "
        "[Sök] (Function web_search; unavailable for this turn) och "
        f"[Beräkna] (MCP {SERVER}, tool räkna/procent%20; unavailable for this turn)."
    )


@pytest.mark.parametrize(
    "text",
    [
        f"`{LINK}`",
        f"``before `{LINK}` after``",
        f"```md\n{LINK}\n```",
        f"~~~~\n{LINK}\n~~~~",
        f"    {LINK}",
        f"\t{LINK}",
        f"\\{LINK}",
        f"!{LINK}",
        "[Klartext](https://example.com) @Klartext [Klartext]",
    ],
)
def test_examples_and_ordinary_text_do_not_activate_references(text: str):
    assert parse_instruction_references(text) == ()
    assert render_instruction_references(text) == text


def test_fences_and_inline_code_end_at_their_matching_delimiter():
    text = f"````\n```\n{LINK}\n````\n`example` {LINK}"
    references = parse_instruction_references(text)
    assert len(references) == 1
    assert references[0].end == len(text)


def test_escaped_first_backtick_does_not_hide_the_remaining_code_delimiter():
    assert parse_instruction_references(f"\\``{LINK}`") == ()


def test_escaped_label_is_text_and_never_changes_target_identity():
    reference = parse_instruction_references(
        f"[Klar\\[text\\] \\ slutför](eneo-skill:{SKILL}@{REVISION})"
    )[0]
    assert reference.label == "Klar[text] \\ slutför"
    assert reference.target == SkillInstructionReference(
        skill_id=SKILL, revision_id=REVISION
    )


@pytest.mark.parametrize(
    "target",
    [
        "eneo-skill:not-a-uuid@revision",
        f"eneo-skill:{SKILL}",
        "eneo-function:unknown",
        "eneo-mcp:https://evil.example",
        f"eneo-tool:{SERVER}/",
        f"eneo-tool:{SERVER}/bad%ZZ",
        f"eneo-tool:{SERVER}/%00",
        f"eneo-tool:{SERVER}/%FF",
    ],
)
def test_malformed_reserved_references_are_rejected(target: str):
    with pytest.raises(
        BadRequestException, match="Invalid Skill instruction reference"
    ):
        parse_instruction_references(f"[Name]({target})")


def test_repeated_mentions_do_not_consume_the_unique_skill_budget():
    references = parse_instruction_references(" ".join([LINK] * 101))
    assert len(references) == 101
    assert len({reference.target for reference in references}) == 1
