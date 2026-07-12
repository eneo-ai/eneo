"""Pattern Registry tests.

Covers: `Pattern` dataclass shape (structural planner-strategy fields
only), registry immutability, version constant, exact seed ids,
slot-vocabulary anchored on the live `ai_builder_slot_vocabulary`
leaf export, and negative-pattern bite asserted against live FCM callables.
Plain test class, no fixtures beyond scoped helpers, direct imports.

User-facing copy (labels, localized text, help prose) is explicitly NOT
pinned here; that surface lives on the Question Catalog and is never
reachable via `Pattern`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import FrozenInstanceError

import pytest

from eneo.flows.ai_builder.ai_builder_slot_vocabulary import (
    KNOWN_REQUIREMENT_SLOT_NAMES,
)
from eneo.flows.ai_builder.pattern_registry import (
    CHAIN_STEP_DESCRIPTORS,
    COMPILED_CHAIN_PATTERN_IDS,
    PATTERN_REGISTRY,
    PATTERN_REGISTRY_VERSION,
    PLANNER_ONLY_CHAIN_PATTERN_IDS,
    Pattern,
    question_template_ids_for_slot,
)
from eneo.flows.enums import (
    FlowInputType,
    FlowOutputMode,
    FlowOutputType,
)
from eneo.flows.flow_capability_manifest import (
    CAPABILITY_REGISTRY,
    supports_step_io_tuple,
)

# Exact seed pinned here — the canonical archetype list lives in code,
# not in any external target band. Changing this set is a deliberate
# surface change and should be a one-line diff against both registry
# and test.
_EXPECTED_POSITIVE_IDS: frozenset[str] = frozenset(
    {
        "summarize_text",
        "extract_structured_fields",
        "json_to_structured_payload",
        "json_to_text_summary",
        "json_to_artifact_report",
        "document_to_structured_report",
        "document_to_docx_template",
        "document_to_pdf_report",
        "audio_transcription",
        "audio_to_artifact_report",
        "text_to_artifact_report",
        "comparison",
        "sectioned_form_intake",
        "form_field_runtime_inputs",
        "source_parallel_extractions_to_final_text",
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
    def test_pattern_version_is_ten(self) -> None:
        assert PATTERN_REGISTRY_VERSION == 10

    def test_pattern_is_frozen_with_structural_fields(self) -> None:
        pattern = Pattern(
            id="fixture",
            examples=(),
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
                negative_examples=(),
                required_architectural_slots=(),
                question_template_ids=(),
                polarity="positive",
            )

    def test_pattern_chain_steps_defaults_to_empty_tuple(self) -> None:
        """`chain_steps` is an optional structural descriptor for patterns
        whose canonical realisation is multi-step (e.g. a quality chain,
        a sectioned intake, a template-fill pipeline). Patterns that
        describe a single-step shape leave it empty — the default is
        `()` so adding the field does not require updating the existing
        single-step seed."""
        pattern = Pattern(
            id="fixture",
            examples=(),
            negative_examples=(),
            required_architectural_slots=(),
            question_template_ids=(),
            polarity="positive",
        )
        assert pattern.chain_steps == ()

    def test_pattern_rejects_chain_steps_without_chain_kind(self) -> None:
        with pytest.raises(ValueError, match="chain_kind"):
            Pattern(
                id="fixture",
                examples=(),
                negative_examples=(),
                required_architectural_slots=(),
                question_template_ids=(),
                polarity="positive",
                chain_steps=("compiled_step",),
            )

    def test_pattern_rejects_chain_kind_without_chain_steps(self) -> None:
        with pytest.raises(ValueError, match="without chain_steps"):
            Pattern(
                id="fixture",
                examples=(),
                negative_examples=(),
                required_architectural_slots=(),
                question_template_ids=(),
                polarity="positive",
                chain_kind="compiled",
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
        """Exact-id pin. This test is the canonical source of truth for
        the seeded archetypes. Changing the seed is a deliberate one-line
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

    def test_source_parallel_extractions_pattern_is_seeded(self) -> None:
        """Canonical positive shape for flows where one source feeds
        multiple parallel structured extractions that a final text step
        composes from. Without it, the planner has no worked example of
        the fan-in shape and tends to daisy-chain extractions through
        `previous_step` so each later extraction loses sight of the
        original material.
        """
        pattern = PATTERN_REGISTRY.get("source_parallel_extractions_to_final_text")
        assert pattern is not None, (
            "source_parallel_extractions_to_final_text must be registered"
        )
        assert pattern.polarity == "positive"
        assert "primary_runtime_input" in pattern.required_architectural_slots
        assert "terminal_output" in pattern.required_architectural_slots

    def test_json_source_patterns_are_seeded_as_first_class_runtime_inputs(
        self,
    ) -> None:
        for pattern_id in (
            "json_to_structured_payload",
            "json_to_text_summary",
            "json_to_artifact_report",
        ):
            pattern = PATTERN_REGISTRY.get(pattern_id)
            assert pattern is not None, f"{pattern_id} must be registered"
            assert pattern.polarity == "positive"
            assert "primary_runtime_input" in pattern.required_architectural_slots
            assert "terminal_output" in pattern.required_architectural_slots


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

    def test_multi_step_patterns_declare_chain_steps(self) -> None:
        """Patterns whose canonical realisation is a multi-step pipeline
        must declare their step sequence in `chain_steps` so the compiler and
        controller can reason about the shape. Single-step patterns like
        `summarize_text`, `extract_structured_fields`, `audio_transcription`
        leave it empty; the seed below is the canonical set and any
        addition must be a deliberate one-line diff against both registry
        and this test."""
        multi_step_seed: frozenset[str] = frozenset(
            {
                "audio_to_artifact_report",
                "sectioned_form_intake",
                "document_to_docx_template",
            }
        )
        for pattern_id in multi_step_seed:
            pattern = PATTERN_REGISTRY[pattern_id]
            assert pattern.chain_steps, (
                f"{pattern_id}: multi-step canonical pattern must declare "
                f"non-empty chain_steps; got {pattern.chain_steps!r}"
            )

    def test_chain_bearing_patterns_are_explicitly_classified(self) -> None:
        """Every chain-bearing pattern needs an owner.

        Compiler-backed chains are turned into backend-owned skeleton steps;
        planner-only chains are prompt metadata only. A new chain pattern
        must choose one category explicitly so compiler behavior cannot drift
        behind the planner-visible registry.
        """

        chain_bearing_ids = frozenset(
            pattern.id for pattern in PATTERN_REGISTRY.values() if pattern.chain_steps
        )
        classified_ids = COMPILED_CHAIN_PATTERN_IDS | PLANNER_ONLY_CHAIN_PATTERN_IDS

        assert COMPILED_CHAIN_PATTERN_IDS.isdisjoint(PLANNER_ONLY_CHAIN_PATTERN_IDS)
        assert chain_bearing_ids == classified_ids

    def test_every_chain_step_token_is_declared_in_manifest(self) -> None:
        """Chain tokens are backend/compiler vocabulary.

        The Pattern Registry chooses which token sequence belongs to a
        pattern and owns the human-readable label for each token. Concrete
        compiler step text lives in the create intent compiler. This guard makes
        token renames fail in tests instead of silently drifting between the
        planner prompt and backend compiler.
        """

        registry_tokens = frozenset(
            chain_step
            for pattern in PATTERN_REGISTRY.values()
            for chain_step in pattern.chain_steps
        )
        manifest_tokens = frozenset(CHAIN_STEP_DESCRIPTORS)

        assert registry_tokens == manifest_tokens
        for token, descriptor in CHAIN_STEP_DESCRIPTORS.items():
            assert descriptor.token == token
            assert descriptor.label.strip(), f"{token}: empty chain-step label"


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
        """`question_template_ids` forward-references the Question Catalog.
        This test pins the tuple-of-strings shape; live resolution against
        the catalog is asserted in `test_question_catalog.py`."""
        for pattern in PATTERN_REGISTRY.values():
            for qid in pattern.question_template_ids:
                assert isinstance(qid, str), (
                    f"{pattern.id}: question_template_id {qid!r} must be a string"
                )
                assert qid.strip(), f"{pattern.id}: empty question_template_id rejected"


class TestPatternRegistryPublicApi:
    """Public planner-strategy entry points for slot-to-question lookup."""

    def test_question_template_ids_for_slot_returns_declared_qids(self) -> None:
        """`summarize_text` declares `primary_runtime_input` and
        `terminal_output` as both slots and question_template_ids. The
        lookup must return the qids in declaration order."""
        qids = question_template_ids_for_slot("summarize_text", "primary_runtime_input")
        assert qids == ("primary_runtime_input",)
        qids = question_template_ids_for_slot("summarize_text", "terminal_output")
        assert qids == ("terminal_output",)

    def test_question_template_ids_for_slot_returns_empty_for_unknown_slot(
        self,
    ) -> None:
        """A slot the pattern does not declare yields `()` — not an
        exception, because 'does this pattern care about slot X' is a
        valid question a consumer may ask repeatedly."""
        assert (
            question_template_ids_for_slot("summarize_text", "pdf_generation_mode")
            == ()
        )

    def test_question_template_ids_for_slot_raises_for_unknown_pattern_id(
        self,
    ) -> None:
        """A typo in `pattern_id` should fail loudly. Returning `()`
        would mask a programmer error — the caller almost certainly
        meant a real pattern id."""
        with pytest.raises(KeyError):
            question_template_ids_for_slot("no_such_pattern", "primary_runtime_input")

    def test_form_field_runtime_inputs_declares_runtime_metadata_slot(
        self,
    ) -> None:
        """The form-field archetype owns runtime-input metadata discovery."""
        pattern = PATTERN_REGISTRY["form_field_runtime_inputs"]
        assert "runtime_metadata_fields" in pattern.required_architectural_slots, (
            "form_field_runtime_inputs lost `runtime_metadata_fields` from "
            "required_architectural_slots"
        )
        assert "runtime_metadata_fields" in pattern.question_template_ids, (
            "form_field_runtime_inputs lost `runtime_metadata_fields` from "
            "question_template_ids"
        )

    def test_runtime_metadata_fields_has_one_positive_required_slot_owner(
        self,
    ) -> None:
        owners = tuple(
            pattern.id
            for pattern in PATTERN_REGISTRY.values()
            if pattern.polarity == "positive"
            and "runtime_metadata_fields" in pattern.required_architectural_slots
        )

        assert owners == ("form_field_runtime_inputs",)

    def test_runtime_metadata_fields_has_one_positive_question_template_owner(
        self,
    ) -> None:
        owners = tuple(
            pattern.id
            for pattern in PATTERN_REGISTRY.values()
            if pattern.polarity == "positive"
            and "runtime_metadata_fields" in pattern.question_template_ids
        )

        assert owners == ("form_field_runtime_inputs",)
