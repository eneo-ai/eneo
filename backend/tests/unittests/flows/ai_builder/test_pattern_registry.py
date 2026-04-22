"""Pattern Registry scaffold tests (Phase A.4).

Covers: `Pattern` dataclass shape (structural planner-strategy fields
only), registry immutability, version constant, exact seed ids,
slot-vocabulary anchored on the live `ai_builder_slot_vocabulary`
leaf export, and negative-pattern bite asserted against live FCM callables.
Matches the `test_ai_builder_recipe_selector.py` idiom — plain test
class, no fixtures beyond scoped helpers, direct imports.

User-facing copy (labels, localized text, help prose) is explicitly NOT
pinned here; that surface lives on Question Catalog (A.4b) and is never
reachable via `Pattern`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import FrozenInstanceError

import pytest

from intric.flows.ai_builder.ai_builder_slot_vocabulary import (
    KNOWN_REQUIREMENT_SLOT_NAMES,
)
from intric.flows.ai_builder.pattern_registry import (
    PATTERN_REGISTRY,
    PATTERN_REGISTRY_VERSION,
    Pattern,
)
from intric.flows.enums import (
    FlowInputType,
    FlowOutputMode,
    FlowOutputType,
)
from intric.flows.flow_capability_manifest import (
    CAPABILITY_REGISTRY,
    supports_step_io_tuple,
)

# Exact seed pinned here — the 6-8/1-2 count band from the plan is
# advisory; the canonical list lives in code. Changing this set is a
# deliberate surface change and should be a one-line diff against both
# registry and test.
_EXPECTED_POSITIVE_IDS: frozenset[str] = frozenset(
    {
        "summarize_text",
        "extract_structured_fields",
        "document_to_structured_report",
        "document_to_docx_template",
        "document_to_pdf_report",
        "audio_transcription",
        "multi_step_quality_chain",
        "comparison",
        "sectioned_form_intake",
    }
)

_EXPECTED_NEGATIVE_IDS: frozenset[str] = frozenset(
    {
        "image_input_pipeline",
        "template_fill_non_docx",
    }
)


def _assert_image_input_not_exposed() -> None:
    cap = CAPABILITY_REGISTRY["input_image"]
    assert cap.exposure == "not_exposed", (
        f"image_input_pipeline negative lost FCM bite: input_image now has "
        f"exposure={cap.exposure!r} (expected 'not_exposed')"
    )


def _assert_template_fill_requires_docx() -> None:
    for output_type in (
        FlowOutputType.TEXT,
        FlowOutputType.PDF,
        FlowOutputType.JSON,
    ):
        assert not supports_step_io_tuple(
            input_type=FlowInputType.TEXT,
            output_type=output_type,
            output_mode=FlowOutputMode.TEMPLATE_FILL,
        ), (
            f"template_fill_non_docx negative lost FCM bite: FCM now allows "
            f"output_mode=template_fill with output_type={output_type.value!r} "
            f"(should require DOCX)"
        )


# Map negative pattern id → live-FCM assertion the test must satisfy.
# A negative pattern added without a live assertion here fails
# `test_every_negative_has_live_fcm_assertion`, forcing the author to
# name the engine-truth anchor instead of shipping prose.
_NEGATIVE_FCM_ASSERTIONS: dict[str, Callable[[], None]] = {
    "image_input_pipeline": _assert_image_input_not_exposed,
    "template_fill_non_docx": _assert_template_fill_requires_docx,
}


class TestPatternDataclass:
    def test_pattern_version_is_one(self) -> None:
        assert PATTERN_REGISTRY_VERSION == 1

    def test_pattern_is_frozen_with_structural_fields(self) -> None:
        pattern = Pattern(
            id="fixture",
            examples=(),
            retrieval_hints=(),
            negative_examples=(),
            required_architectural_slots=(),
            question_template_ids=(),
            polarity="positive",
        )
        assert pattern.id == "fixture"
        assert pattern.polarity == "positive"
        with pytest.raises(FrozenInstanceError):
            pattern.id = "mutated"  # type: ignore[misc]

    def test_pattern_rejects_unknown_polarity(self) -> None:
        """Polarity must be 'positive' or 'negative'. A third value would
        force consumers to handle an undefined strategy — reject at
        construction time instead."""
        with pytest.raises(ValueError, match="polarity"):
            Pattern(
                id="fixture",
                examples=(),
                retrieval_hints=(),
                negative_examples=(),
                required_architectural_slots=(),
                question_template_ids=(),
                polarity="neutral",  # type: ignore[arg-type]
            )

    def test_pattern_rejects_empty_id(self) -> None:
        with pytest.raises(ValueError, match="id"):
            Pattern(
                id="",
                examples=(),
                retrieval_hints=(),
                negative_examples=(),
                required_architectural_slots=(),
                question_template_ids=(),
                polarity="positive",
            )


class TestRegistryInvariants:
    def test_registry_is_immutable(self) -> None:
        """`PATTERN_REGISTRY` must be a `MappingProxyType`; mutation at
        runtime fails. The registry is canonical — consumers must not
        patch it. Same contract as the FCM."""
        first_key = next(iter(PATTERN_REGISTRY))
        with pytest.raises(TypeError):
            PATTERN_REGISTRY["new_key"] = PATTERN_REGISTRY[first_key]  # type: ignore[index]
        with pytest.raises(TypeError):
            del PATTERN_REGISTRY[first_key]  # type: ignore[misc]

    def test_registry_matches_expected_seed_ids(self) -> None:
        """Exact-id pin. The plan's '6-8 positive + 1-2 negative' band is
        advisory; this test is the canonical source of truth for the
        seeded archetypes. Changing the seed is a deliberate one-line
        diff against both registry and `_EXPECTED_*_IDS` above."""
        positive_ids = frozenset(
            p.id for p in PATTERN_REGISTRY.values() if p.polarity == "positive"
        )
        negative_ids = frozenset(
            p.id for p in PATTERN_REGISTRY.values() if p.polarity == "negative"
        )
        assert positive_ids == _EXPECTED_POSITIVE_IDS, (
            f"Positive seed drift: got {sorted(positive_ids)}, expected "
            f"{sorted(_EXPECTED_POSITIVE_IDS)}"
        )
        assert negative_ids == _EXPECTED_NEGATIVE_IDS, (
            f"Negative seed drift: got {sorted(negative_ids)}, expected "
            f"{sorted(_EXPECTED_NEGATIVE_IDS)}"
        )

    def test_pattern_ids_are_unique(self) -> None:
        """Registry key must equal `pattern.id`. Drift means a consumer
        traversing `.values()` sees a different id than one traversing
        the keys."""
        for key, pattern in PATTERN_REGISTRY.items():
            assert key == pattern.id, (
                f"Registry key {key!r} does not match pattern.id {pattern.id!r}"
            )
        ids = [pattern.id for pattern in PATTERN_REGISTRY.values()]
        assert len(ids) == len(set(ids)), f"Duplicate pattern ids in registry: {ids}"


class TestPositivePatternContract:
    @pytest.fixture
    def positive_patterns(self) -> list[Pattern]:
        return [p for p in PATTERN_REGISTRY.values() if p.polarity == "positive"]

    def test_every_positive_declares_at_least_one_architectural_slot(
        self, positive_patterns: list[Pattern]
    ) -> None:
        """A positive archetype exists to drive planner discovery toward
        architectural decisions. A positive with zero slots has no
        planner bite — either it's miscategorized or the slot vocabulary
        needs widening."""
        for pattern in positive_patterns:
            assert len(pattern.required_architectural_slots) >= 1, (
                f"{pattern.id}: positive pattern must declare >=1 "
                "required_architectural_slot"
            )

    def test_every_declared_slot_is_in_live_vocabulary(
        self, positive_patterns: list[Pattern]
    ) -> None:
        """A Pattern may only reference slot names that exist in
        `ai_builder_slot_vocabulary.KNOWN_REQUIREMENT_SLOT_NAMES`.
        The live export is the single source of truth; a rename there
        without a matching Pattern Registry update fails this test."""
        for pattern in positive_patterns:
            for slot_name in pattern.required_architectural_slots:
                assert slot_name in KNOWN_REQUIREMENT_SLOT_NAMES, (
                    f"{pattern.id} references unknown slot "
                    f"{slot_name!r}; live vocabulary is "
                    f"{sorted(KNOWN_REQUIREMENT_SLOT_NAMES)}"
                )


class TestNegativePatternContract:
    @pytest.fixture
    def negative_patterns(self) -> list[Pattern]:
        return [p for p in PATTERN_REGISTRY.values() if p.polarity == "negative"]

    def test_negative_fcm_assertions_keys_equal_negative_ids(
        self, negative_patterns: list[Pattern]
    ) -> None:
        """Bidirectional coupling: `_NEGATIVE_FCM_ASSERTIONS` must key
        on exactly the negative-pattern id set. A stale key (pattern
        renamed or removed but assertion left behind) fails here, same
        as a missing key."""
        negative_ids = frozenset(p.id for p in negative_patterns)
        assertion_keys = frozenset(_NEGATIVE_FCM_ASSERTIONS.keys())
        assert assertion_keys == negative_ids, (
            f"_NEGATIVE_FCM_ASSERTIONS keys drifted from negative-pattern "
            f"ids: stale keys {sorted(assertion_keys - negative_ids)}, "
            f"missing keys {sorted(negative_ids - assertion_keys)}"
        )

    def test_every_negative_has_live_fcm_assertion(
        self, negative_patterns: list[Pattern]
    ) -> None:
        """Every negative archetype must name the FCM callable that
        rejects its canonical shape. If the FCM ever legalizes one of
        these shapes (e.g. IMAGE input becomes exposed, TEMPLATE_FILL
        stops requiring DOCX), the corresponding assertion fires and CI
        surfaces the stale negative."""
        for pattern in negative_patterns:
            _NEGATIVE_FCM_ASSERTIONS[pattern.id]()


class TestQuestionTemplateIdReferences:
    def test_question_template_ids_are_strings(self) -> None:
        """`question_template_ids` forward-references the A.4b Question
        Catalog. A.4 pins only the tuple-of-strings shape; live
        resolution is an A.5 CI test once Question Catalog lands."""
        for pattern in PATTERN_REGISTRY.values():
            for qid in pattern.question_template_ids:
                assert isinstance(qid, str), (
                    f"{pattern.id}: question_template_id {qid!r} must be a string"
                )
                assert qid.strip(), f"{pattern.id}: empty question_template_id rejected"
