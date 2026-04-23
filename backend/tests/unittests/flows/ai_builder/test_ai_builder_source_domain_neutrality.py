"""Lockdown: banned specialty tokens must not appear in any string
literal inside the AI Builder source tree.

The AI Builder is general-purpose — it helps users build procurement,
onboarding, transcription, extraction, comparison, support-triage, and
template-fill flows. Swedish decision-support / case-management
vocabulary AND the English `decision support` compound must not appear
in any detection tuple, heuristic phrase list, prompt fragment,
knowledge-pack section, or code comment inside
`backend/src/intric/flows/ai_builder/`.

User-visible labels are pinned by
`TestDomainNeutrality::test_no_banned_tokens_in_any_rendered_template`
in `test_question_catalog.py`. This test covers the complementary
surface: the source-level detection and prompt-building code.

Any future change that reintroduces specialty vocabulary fails here
before landing.
"""

from __future__ import annotations

from pathlib import Path

# Banned tokens mirror the catalog lockdown list. Substring matches
# (not whole-word) so compounds like `beslutsunderlagsmall` or
# `handläggaren` are caught too. Keep in sync with
# `TestDomainNeutrality._BANNED_SPECIALTY_TOKENS` in
# `test_question_catalog.py`.
_BANNED_SPECIALTY_TOKENS: tuple[str, ...] = (
    "tjänsteskriv",
    "beslutsunderlag",
    "beslutsstöd",
    "beslutsförslag",
    "nämnden",
    "nämnder",
    "remiss",
    "handläggar",
    "ärendenummer",
    "decision support",
    "decision-support",
    "kommunärende",
    "municipal case",
    "guldexempel",
    "kommunanalys",
    "ärendeanalys",
    "ansvarig_namnd",
    "juridiska risker",
    "ekonomiska konsekvenser",
)

_AI_BUILDER_SRC = (
    Path(__file__).resolve().parent.parent.parent.parent.parent
    / "src"
    / "intric"
    / "flows"
    / "ai_builder"
)


class TestSourceDomainNeutrality:
    def test_no_banned_tokens_in_any_ai_builder_source_file(self) -> None:
        assert _AI_BUILDER_SRC.is_dir(), (
            f"AI Builder source directory not found: {_AI_BUILDER_SRC}"
        )

        offenders: list[tuple[str, int, str, str]] = []
        for path in sorted(_AI_BUILDER_SRC.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            lowered = text.casefold()
            for token in _BANNED_SPECIALTY_TOKENS:
                if token.casefold() not in lowered:
                    continue
                for line_no, line in enumerate(text.splitlines(), start=1):
                    if token.casefold() in line.casefold():
                        offenders.append(
                            (
                                str(
                                    path.relative_to(
                                        _AI_BUILDER_SRC.parent.parent.parent
                                    )
                                ),
                                line_no,
                                token,
                                line.strip(),
                            )
                        )

        assert not offenders, (
            "Banned specialty tokens found in AI Builder source:\n"
            + "\n".join(
                f"  {path}:{line_no} [{token}] {snippet}"
                for path, line_no, token, snippet in offenders
            )
        )
