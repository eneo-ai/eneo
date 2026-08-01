"""Freeze semantic cases and their deterministic classifier-boundary contracts.

The exhaustive cases protect response lifecycle and source chronology. Three
representative provider outputs protect prompt, parse, bias, and citation
acceptance. Passing them is not proof of the selected model's semantic accuracy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Self, cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from eneo.completion_models.domain.model_kwargs_capabilities import (
    ModelKwargCapability,
    SupportedModelKwargs,
)
from eneo.completion_models.infrastructure.completion_service import (
    ResolvedCompletionModelRoute,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    metadata_for_assistant_question,
)
from eneo.flows.ai_builder.ai_builder_discovery_runtime import (
    build_slot_classification_input,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_event_models import (
    StructuredQuestionOptionPayload,
    StructuredQuestionPayload,
)
from eneo.flows.ai_builder.ai_builder_slot_classifier import (
    ClassifiedEvidence,
    SlotClassificationBias,
    SlotClassificationSource,
    classify_slots,
)
from eneo.flows.ai_builder.ai_builder_slot_vocabulary import (
    LLM_RESOLVABLE_SLOT_NAMES,
)
from eneo.flows.ai_builder.ai_builder_user_question_metadata import (
    prepare_user_question_metadata,
)
from eneo.flows.ai_builder.question_catalog import (
    QUESTION_CATALOG,
    Locale,
    legal_slot_values,
    render_question,
)

CORPUS_SCHEMA_VERSION = 1
MAX_SOURCE_TEXT_LENGTH = 240
LOCALES: tuple[Locale, ...] = ("sv", "en")
SCENARIO_KINDS = frozenset(
    {
        "paraphrase",
        "negation",
        "ambiguity",
        "unrelated_or_adversarial_mention",
        "chronology",
    }
)
CHRONOLOGY_SUBTYPES = frozenset({"later_correction", "unrelated_topic_change"})
CORPUS_PATH = (
    Path(__file__).resolve().parents[4]
    / "scripts"
    / "ai_builder_semantic_classifier_cases.json"
)

ScenarioKind = Literal[
    "paraphrase",
    "negation",
    "ambiguity",
    "unrelated_or_adversarial_mention",
    "chronology",
]
ChronologySubtype = Literal["later_correction", "unrelated_topic_change"]
CitationSourceIndex = Annotated[int, Field(ge=0)]


class SemanticScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: str = Field(
        min_length=8,
        max_length=120,
        pattern=r"^[a-z][a-z0-9-]+$",
    )
    kind: ScenarioKind
    source_texts: list[str] = Field(min_length=1, max_length=2)
    expected_value: str | None
    chronology_subtype: ChronologySubtype | None
    citation_source_index: CitationSourceIndex | None

    @field_validator("source_texts")
    @classmethod
    def validate_source_texts(cls, source_texts: list[str]) -> list[str]:
        if any(
            text != text.strip() or not text or len(text) > MAX_SOURCE_TEXT_LENGTH
            for text in source_texts
        ):
            raise ValueError("source texts must be trimmed, nonempty, and bounded")
        return source_texts

    @model_validator(mode="after")
    def validate_scenario_shape(self) -> Self:
        if self.kind == "chronology":
            if self.chronology_subtype is None or len(self.source_texts) != 2:
                raise ValueError(
                    "chronology requires a subtype and two ordered sources"
                )
        elif self.chronology_subtype is not None or len(self.source_texts) != 1:
            raise ValueError("only chronology may carry a subtype or multiple sources")

        if self.expected_value is None:
            if self.citation_source_index is not None:
                raise ValueError("unresolved scenarios cannot select a citation source")
        elif self.citation_source_index is None or self.citation_source_index >= len(
            self.source_texts
        ):
            raise ValueError("resolved scenarios require an in-range citation source")
        return self


class SemanticBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    slot_name: str
    locale: Locale
    scenarios: list[SemanticScenario] = Field(min_length=5, max_length=5)


class SemanticCorpus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[CORPUS_SCHEMA_VERSION]
    bundles: list[SemanticBundle] = Field(min_length=14, max_length=14)


@dataclass(frozen=True, slots=True)
class ExactLabelCase:
    id: str
    slot_name: str
    locale: Locale
    option_value: str
    label: str


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    parsed: dict[str, object] = {}
    for key, value in pairs:
        if key in parsed:
            raise ValueError(f"duplicate JSON key: {key}")
        parsed[key] = value
    return parsed


def _load_corpus() -> SemanticCorpus:
    raw: object = json.loads(
        CORPUS_PATH.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_json_keys,
    )
    return SemanticCorpus.model_validate(raw)


def _exact_label_cases() -> tuple[ExactLabelCase, ...]:
    cases: list[ExactLabelCase] = []
    for slot_name in sorted(LLM_RESOLVABLE_SLOT_NAMES):
        for locale in LOCALES:
            for option in render_question(slot_name, locale).options:
                cases.append(
                    ExactLabelCase(
                        id=f"{locale}-{slot_name}-{option.id}-exact-label",
                        slot_name=slot_name,
                        locale=locale,
                        option_value=option.value,
                        label=option.label,
                    )
                )
    return tuple(cases)


def _canonical_question(slot_name: str, locale: Locale) -> StructuredQuestionPayload:
    rendered = render_question(slot_name, locale)
    return StructuredQuestionPayload(
        question_id=rendered.id,
        question=rendered.question,
        options=[
            StructuredQuestionOptionPayload(
                id=option.id,
                label=option.label,
                value=option.value,
                description=option.description,
            )
            for option in rendered.options
        ],
        selection_mode="single",
        allow_custom=True,
    )


def _route() -> ResolvedCompletionModelRoute:
    return ResolvedCompletionModelRoute(
        litellm_model="openai/semantic-contract-test",
        litellm_kwargs={},
        supported_model_kwargs=SupportedModelKwargs(
            temperature=ModelKwargCapability(supported=True)
        ),
    )


def _mock_response(slots: list[dict[str, object]]) -> MagicMock:
    message = MagicMock()
    message.content = json.dumps(
        {
            "slots": slots,
            "file_roles": [],
            "form_intake": None,
            "example_output_constraints": None,
            "secondary_obligations": [],
            "assumptions": [],
            "contradictions": [],
        },
        ensure_ascii=False,
    )
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _resolved_provider_slot(
    *,
    slot_name: str,
    value: str,
    source: SlotClassificationSource,
) -> dict[str, object]:
    return {
        "slot_name": slot_name,
        "value": value,
        "confidence": "high",
        "reason": "The cited source states the constrained choice.",
        "evidence": [{"source_id": source.source_id, "quote": source.text}],
        "evidence_level": "explicit",
    }


CORPUS = _load_corpus()
EXACT_LABEL_CASES = _exact_label_cases()
SEMANTIC_CASES = tuple(
    scenario for bundle in CORPUS.bundles for scenario in bundle.scenarios
)
CLASSIFIER_BOUNDARY_CASES = (
    EXACT_LABEL_CASES[0],
    next(case for case in EXACT_LABEL_CASES if case.locale == "en"),
    EXACT_LABEL_CASES[-1],
)
ALLOWED_SLOT_VALUES = {
    slot_name: legal_slot_values(slot_name)
    for slot_name in sorted(LLM_RESOLVABLE_SLOT_NAMES)
}


def test_semantic_corpus_schema_and_coverage_are_frozen() -> None:
    expected_bundle_keys = {
        (slot_name, locale)
        for slot_name in LLM_RESOLVABLE_SLOT_NAMES
        for locale in LOCALES
    }
    assert CORPUS.schema_version == CORPUS_SCHEMA_VERSION
    assert {(bundle.slot_name, bundle.locale) for bundle in CORPUS.bundles} == (
        expected_bundle_keys
    )

    scenario_ids: list[str] = []
    source_texts: list[str] = []
    chronology_by_slot: dict[str, set[ChronologySubtype]] = {
        slot_name: set() for slot_name in LLM_RESOLVABLE_SLOT_NAMES
    }
    catalog_labels = {
        label
        for template in QUESTION_CATALOG.values()
        for option in template.options
        for label in (option.label_sv, option.label_en)
    }

    for bundle in CORPUS.bundles:
        assert bundle.slot_name in QUESTION_CATALOG
        assert {scenario.kind for scenario in bundle.scenarios} == SCENARIO_KINDS
        for scenario in bundle.scenarios:
            scenario_ids.append(scenario.id)
            source_texts.extend(scenario.source_texts)
            if scenario.expected_value is not None:
                assert scenario.expected_value in legal_slot_values(bundle.slot_name)
            if scenario.kind in {
                "ambiguity",
                "unrelated_or_adversarial_mention",
            }:
                assert scenario.expected_value is None
            else:
                assert scenario.expected_value is not None
            if scenario.chronology_subtype is not None:
                chronology_by_slot[bundle.slot_name].add(scenario.chronology_subtype)
                assert scenario.citation_source_index == (
                    1 if scenario.chronology_subtype == "later_correction" else 0
                )

    assert len(scenario_ids) == 70
    assert len(scenario_ids) == len(set(scenario_ids))
    assert len(source_texts) == len({text.casefold() for text in source_texts})
    assert all(0 < len(text) <= MAX_SOURCE_TEXT_LENGTH for text in source_texts)
    assert catalog_labels.isdisjoint(source_texts)
    assert all(
        subtypes == CHRONOLOGY_SUBTYPES for subtypes in chronology_by_slot.values()
    )


def test_exact_label_matrix_covers_every_catalog_option_in_both_locales() -> None:
    assert len(LLM_RESOLVABLE_SLOT_NAMES) == 7
    assert (
        len({(case.slot_name, case.option_value) for case in EXACT_LABEL_CASES}) == 32
    )
    assert len(EXACT_LABEL_CASES) == 64
    assert len({case.id for case in EXACT_LABEL_CASES}) == 64
    assert {
        (case.slot_name, case.locale, case.option_value, case.label)
        for case in EXACT_LABEL_CASES
    } == {
        (
            slot_name,
            locale,
            option.value,
            option.label_sv if locale == "sv" else option.label_en,
        )
        for slot_name in LLM_RESOLVABLE_SLOT_NAMES
        for locale in LOCALES
        for option in QUESTION_CATALOG[slot_name].options
    }


@pytest.mark.parametrize(
    "case",
    EXACT_LABEL_CASES,
    ids=[case.id for case in EXACT_LABEL_CASES],
)
def test_exact_label_uses_neutral_response_lifecycle(
    case: ExactLabelCase,
) -> None:
    question = _canonical_question(case.slot_name, case.locale)
    assistant_message = ConversationMessage(
        message_id=f"assistant-{case.id}",
        role="assistant",
        content=question.question,
        metadata=metadata_for_assistant_question(question),
    )
    prepared = prepare_user_question_metadata(
        conversation=[assistant_message],
        message=case.label,
        question_answer=None,
    )

    assert prepared.metadata == {"question_response": {"question_id": case.slot_name}}
    assert "question_answer" not in prepared.metadata

    user_message = ConversationMessage(
        message_id=f"user-{case.id}",
        role="user",
        content=case.label,
        metadata=prepared.metadata,
    )
    classification_input = build_slot_classification_input(
        [assistant_message, user_message],
        None,
    )
    assert len(classification_input.sources) == 1
    source = classification_input.sources[0]
    assert source.text == case.label
    assert source.question_id == case.slot_name


@pytest.mark.parametrize(
    "case",
    CLASSIFIER_BOUNDARY_CASES,
    ids=[case.id for case in CLASSIFIER_BOUNDARY_CASES],
)
@pytest.mark.asyncio
async def test_representative_exact_labels_cross_prompt_parse_and_citation_boundary(
    case: ExactLabelCase,
) -> None:
    question = _canonical_question(case.slot_name, case.locale)
    assistant_message = ConversationMessage(
        message_id=f"assistant-{case.id}",
        role="assistant",
        content=question.question,
        metadata=metadata_for_assistant_question(question),
    )
    prepared = prepare_user_question_metadata(
        conversation=[assistant_message],
        message=case.label,
        question_answer=None,
    )
    user_message = ConversationMessage(
        message_id=f"user-{case.id}",
        role="user",
        content=case.label,
        metadata=prepared.metadata,
    )
    classification_input = build_slot_classification_input(
        [assistant_message, user_message],
        None,
    )
    source = classification_input.sources[0]

    litellm_client = MagicMock()
    litellm_client.acompletion = AsyncMock(
        return_value=_mock_response(
            [
                _resolved_provider_slot(
                    slot_name=case.slot_name,
                    value=case.option_value,
                    source=source,
                )
            ]
        )
    )
    classification = await classify_slots(
        litellm_client=litellm_client,
        completion_model_route=_route(),
        classification_input=classification_input,
        allowed_slot_values=ALLOWED_SLOT_VALUES,
        tenant_id=UUID(int=1),
        ui_language=case.locale,
        bias=SlotClassificationBias(
            target_slot_name=case.slot_name,
            asked_question_id=case.slot_name,
            answer_source_id=source.source_id,
        ),
    )

    assert classification is not None
    assert len(classification.slots) == 1
    resolved = classification.slots[0]
    assert resolved.slot_name == case.slot_name
    assert resolved.value == case.option_value
    assert resolved.confidence == "high"
    assert resolved.evidence_level == "explicit"
    assert resolved.evidence == (
        ClassifiedEvidence(source_id=source.source_id, quote=case.label),
    )
    assert all(slot.slot_name == case.slot_name for slot in classification.slots)
    litellm_client.acompletion.assert_awaited_once()
    provider_messages = cast(
        list[dict[str, str]],
        litellm_client.acompletion.await_args.kwargs["messages"],
    )
    prompt = "\n".join(message["content"] for message in provider_messages)
    assert f"slot `{case.slot_name}`" in prompt
    assert f"Source `{source.source_id}` is the answer" in prompt
    assert case.label in prompt


@pytest.mark.parametrize(
    "scenario",
    SEMANTIC_CASES,
    ids=[scenario.id for scenario in SEMANTIC_CASES],
)
def test_semantic_corpus_preserves_classifier_source_chronology(
    scenario: SemanticScenario,
) -> None:
    conversation = [
        ConversationMessage(
            message_id=f"{scenario.id}-{index}",
            role="user",
            content=text,
        )
        for index, text in enumerate(scenario.source_texts, start=1)
    ]
    classification_input = build_slot_classification_input(conversation, None)
    assert [source.text for source in classification_input.sources] == (
        scenario.source_texts
    )
    assert [source.message_id for source in classification_input.sources] == [
        message.message_id for message in conversation
    ]
