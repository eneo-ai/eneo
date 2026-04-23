"""AI Builder must route specialty prompts deterministically.

When a user asks to build a decision-support memo, a tjänsteskrivelse,
or a remiss flow, the discovery recognizers must classify the input
without falling through to LLM-only discovery. This file fences the
specialty vocabulary that earlier purges removed — a regression would
silently redirect specialty users through the generic LLM path with
lower reliability.

The tests exercise the public entry points:
- `looks_like_case_document_family` and `implies_single_case` in the
  decision engine.
- `infer_answer_signals_from_text`, which routes through
  `_infer_document_kind` and reports `case_documents` for the
  specialty document family.
"""

from __future__ import annotations

import pytest

from intric.flows.ai_builder.ai_builder_discovery_decision_engine import (
    implies_single_case,
    looks_like_case_document_family,
)
from intric.flows.ai_builder.ai_builder_discovery_signal_inference import (
    infer_answer_signals_from_text,
)


class TestCaseDocumentFamilyRecognizer:
    @pytest.mark.parametrize(
        "text",
        [
            "jag vill skriva en tjänsteskrivelse",
            "generera underlag för en remiss",
            "behandla ett kommunärende",
            "analyze a municipal case and draft the memo",
        ],
    )
    def test_specialty_prompts_match_case_document_family(self, text: str) -> None:
        assert looks_like_case_document_family(text), (
            f"{text!r} must match the case-document family"
        )


class TestSingleCaseRecognizer:
    @pytest.mark.parametrize(
        "text",
        [
            "jag behandlar ett kommunärende",
            "i only handle one municipal case at a time",
        ],
    )
    def test_single_specialty_case_hints_route_to_single(self, text: str) -> None:
        assert implies_single_case(text), f"{text!r} must imply single-case processing"


class TestSpecialtyDocumentKindInference:
    @pytest.mark.parametrize(
        "text",
        [
            "tjänsteskrivelse inför nämnden",
            "tjänsteskrivelser som ska lämnas in",
            "en remiss från länsstyrelsen",
            "flera remisser per vecka",
            "hantera ett kommunärende",
            "review a municipal case before council",
        ],
    )
    def test_specialty_prompts_infer_case_documents_kind(self, text: str) -> None:
        signals = infer_answer_signals_from_text(text)
        assert "case_documents" in signals.get("document_kind", set()), (
            f"{text!r} must infer document_kind=case_documents "
            f"(got {signals.get('document_kind', set())!r})"
        )
