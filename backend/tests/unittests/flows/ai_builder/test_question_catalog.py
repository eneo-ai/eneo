"""Question Catalog tests.

Covers: `QuestionOption` / `QuestionTemplate` dataclass shape (bilingual
sv/en fields only), registry immutability, version constant, exact
slot-name key pin against the live `KNOWN_REQUIREMENT_SLOT_NAMES`
export, bilingual contract (no partial sv-or-en entries), worked-example
presence, and Pattern Registry back-fill (every positive pattern's
`question_template_ids` resolves in this catalog).

The catalog is user-facing copy — no planner strategy, no FCM truth.
That surface stays on the Pattern Registry and the FCM.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import get_args

import pytest

from intric.flows.ai_builder.ai_builder_discovery_decision_engine import (
    _QUESTION_IMPACT,
)
from intric.flows.ai_builder.ai_builder_discovery_families import QUESTION_FAMILY
from intric.flows.ai_builder.ai_builder_discovery_priority import (
    DISCOVERY_ISSUE_PRIORITY,
)
from intric.flows.ai_builder.ai_builder_slot_vocabulary import (
    KNOWN_REQUIREMENT_SLOT_NAMES,
    DiscoveryFamily,
    DiscoveryImpact,
)
from intric.flows.ai_builder.pattern_registry import PATTERN_REGISTRY
from intric.flows.ai_builder.question_catalog import (
    QUESTION_CATALOG,
    QUESTION_CATALOG_VERSION,
    QuestionOption,
    QuestionTemplate,
    RenderedOption,
    RenderedQuestion,
    legacy_question_id_for_slot,
    legal_slot_values,
    question_ids_for_slot,
    render_question,
    slot_name_for_legacy_question_id,
)

_SLOT_DERIVED_ISSUE_IDS = frozenset(
    legacy_question_id_for_slot(slot_name) for slot_name in KNOWN_REQUIREMENT_SLOT_NAMES
)

_NON_SLOT_PRIORITY_ISSUE_IDS = frozenset(
    {
        "comparison_scope_conflict",
        "case_scope",
        "external_delivery_unsupported",
        "flow_input_architecture",
        "document_kind",
        "comparison_scope",
        "final_pdf_type",
        "output_reader",
        "final_output_scope",
    }
)

_NON_SLOT_FAMILY_ISSUE_IDS = frozenset(
    {
        "comparison_scope_conflict",
        "case_scope",
        "flow_input_architecture",
        "document_kind",
        "comparison_scope",
        "final_pdf_type",
        "output_reader",
        "final_output_scope",
    }
)

_NON_SLOT_IMPACT_ISSUE_IDS = _NON_SLOT_FAMILY_ISSUE_IDS


def _valid_option(
    *,
    option_id: str = "option_a",
    value: str = "value_a",
) -> QuestionOption:
    return QuestionOption(
        id=option_id,
        label_sv="Etikett A",
        label_en="Label A",
        description_sv="Beskrivning A",
        description_en="Description A",
        value=value,
    )


def _valid_template(
    *,
    template_id: str = "primary_runtime_input",
    options: tuple[QuestionOption, ...] | None = None,
    family: DiscoveryFamily = "input_shape",
    priority_base: int = 20,
    impact: DiscoveryImpact = "architecture",
) -> QuestionTemplate:
    return QuestionTemplate(
        id=template_id,
        question_sv="Fråga?",
        question_en="Question?",
        help_sv="Hjälp",
        help_en="Help",
        options=options if options is not None else (_valid_option(),),
        worked_examples_sv=("Exempel ett",),
        worked_examples_en=("Example one",),
        family=family,
        priority_base=priority_base,
        impact=impact,
    )


class TestQuestionOption:
    def test_option_is_frozen(self) -> None:
        option = _valid_option()
        assert option.id == "option_a"
        with pytest.raises(FrozenInstanceError):
            option.id = "mutated"  # type: ignore[misc]

    def test_option_rejects_empty_id(self) -> None:
        with pytest.raises(ValueError, match="id"):
            QuestionOption(
                id="",
                label_sv="Etikett",
                label_en="Label",
                description_sv="Beskrivning",
                description_en="Description",
                value="value",
            )

    def test_option_rejects_empty_value(self) -> None:
        with pytest.raises(ValueError, match="value"):
            QuestionOption(
                id="option_a",
                label_sv="Etikett",
                label_en="Label",
                description_sv="Beskrivning",
                description_en="Description",
                value="",
            )

    def test_option_rejects_empty_label_sv(self) -> None:
        with pytest.raises(ValueError, match="label_sv"):
            QuestionOption(
                id="option_a",
                label_sv="",
                label_en="Label",
                description_sv="Beskrivning",
                description_en="Description",
                value="value",
            )

    def test_option_rejects_empty_label_en(self) -> None:
        with pytest.raises(ValueError, match="label_en"):
            QuestionOption(
                id="option_a",
                label_sv="Etikett",
                label_en="",
                description_sv="Beskrivning",
                description_en="Description",
                value="value",
            )

    def test_option_rejects_empty_description_sv(self) -> None:
        with pytest.raises(ValueError, match="description_sv"):
            QuestionOption(
                id="option_a",
                label_sv="Etikett",
                label_en="Label",
                description_sv="",
                description_en="Description",
                value="value",
            )

    def test_option_rejects_empty_description_en(self) -> None:
        with pytest.raises(ValueError, match="description_en"):
            QuestionOption(
                id="option_a",
                label_sv="Etikett",
                label_en="Label",
                description_sv="Beskrivning",
                description_en="",
                value="value",
            )


class TestQuestionTemplate:
    def test_template_is_frozen(self) -> None:
        template = _valid_template()
        assert template.id == "primary_runtime_input"
        with pytest.raises(FrozenInstanceError):
            template.id = "mutated"  # type: ignore[misc]

    def test_template_rejects_empty_id(self) -> None:
        with pytest.raises(ValueError, match="id"):
            QuestionTemplate(
                id="",
                question_sv="Fråga?",
                question_en="Question?",
                help_sv="Hjälp",
                help_en="Help",
                options=(_valid_option(),),
                worked_examples_sv=("Exempel",),
                worked_examples_en=("Example",),
                family="input_shape",
                priority_base=20,
                impact="architecture",
            )

    def test_template_rejects_empty_question_sv(self) -> None:
        with pytest.raises(ValueError, match="question_sv"):
            QuestionTemplate(
                id="primary_runtime_input",
                question_sv="",
                question_en="Question?",
                help_sv="Hjälp",
                help_en="Help",
                options=(_valid_option(),),
                worked_examples_sv=("Exempel",),
                worked_examples_en=("Example",),
                family="input_shape",
                priority_base=20,
                impact="architecture",
            )

    def test_template_rejects_empty_question_en(self) -> None:
        with pytest.raises(ValueError, match="question_en"):
            QuestionTemplate(
                id="primary_runtime_input",
                question_sv="Fråga?",
                question_en="",
                help_sv="Hjälp",
                help_en="Help",
                options=(_valid_option(),),
                worked_examples_sv=("Exempel",),
                worked_examples_en=("Example",),
                family="input_shape",
                priority_base=20,
                impact="architecture",
            )

    def test_template_rejects_empty_help_sv(self) -> None:
        with pytest.raises(ValueError, match="help_sv"):
            QuestionTemplate(
                id="primary_runtime_input",
                question_sv="Fråga?",
                question_en="Question?",
                help_sv="",
                help_en="Help",
                options=(_valid_option(),),
                worked_examples_sv=("Exempel",),
                worked_examples_en=("Example",),
                family="input_shape",
                priority_base=20,
                impact="architecture",
            )

    def test_template_rejects_empty_help_en(self) -> None:
        with pytest.raises(ValueError, match="help_en"):
            QuestionTemplate(
                id="primary_runtime_input",
                question_sv="Fråga?",
                question_en="Question?",
                help_sv="Hjälp",
                help_en="",
                options=(_valid_option(),),
                worked_examples_sv=("Exempel",),
                worked_examples_en=("Example",),
                family="input_shape",
                priority_base=20,
                impact="architecture",
            )

    def test_template_rejects_empty_worked_examples_sv(self) -> None:
        with pytest.raises(ValueError, match="worked_examples_sv"):
            QuestionTemplate(
                id="primary_runtime_input",
                question_sv="Fråga?",
                question_en="Question?",
                help_sv="Hjälp",
                help_en="Help",
                options=(_valid_option(),),
                worked_examples_sv=(),
                worked_examples_en=("Example",),
                family="input_shape",
                priority_base=20,
                impact="architecture",
            )

    def test_template_rejects_empty_worked_examples_en(self) -> None:
        with pytest.raises(ValueError, match="worked_examples_en"):
            QuestionTemplate(
                id="primary_runtime_input",
                question_sv="Fråga?",
                question_en="Question?",
                help_sv="Hjälp",
                help_en="Help",
                options=(_valid_option(),),
                worked_examples_sv=("Exempel",),
                worked_examples_en=(),
                family="input_shape",
                priority_base=20,
                impact="architecture",
            )

    def test_template_rejects_blank_worked_example_sv(self) -> None:
        with pytest.raises(ValueError, match="worked_examples_sv"):
            QuestionTemplate(
                id="primary_runtime_input",
                question_sv="Fråga?",
                question_en="Question?",
                help_sv="Hjälp",
                help_en="Help",
                options=(_valid_option(),),
                worked_examples_sv=("Exempel ett", "   "),
                worked_examples_en=("Example one",),
                family="input_shape",
                priority_base=20,
                impact="architecture",
            )

    def test_template_rejects_blank_worked_example_en(self) -> None:
        with pytest.raises(ValueError, match="worked_examples_en"):
            QuestionTemplate(
                id="primary_runtime_input",
                question_sv="Fråga?",
                question_en="Question?",
                help_sv="Hjälp",
                help_en="Help",
                options=(_valid_option(),),
                worked_examples_sv=("Exempel ett",),
                worked_examples_en=("Example one", ""),
                family="input_shape",
                priority_base=20,
                impact="architecture",
            )

    def test_template_rejects_no_options(self) -> None:
        """A QuestionTemplate with zero options would render as prose-only
        — the catalog is a structured-choice surface. Reject at
        construction time."""
        with pytest.raises(ValueError, match="options"):
            QuestionTemplate(
                id="primary_runtime_input",
                question_sv="Fråga?",
                question_en="Question?",
                help_sv="Hjälp",
                help_en="Help",
                options=(),
                worked_examples_sv=("Exempel",),
                worked_examples_en=("Example",),
                family="input_shape",
                priority_base=20,
                impact="architecture",
            )

    def test_template_rejects_duplicate_option_ids(self) -> None:
        """Options are resolved by id; a duplicate id makes the catalog
        answer-ambiguous."""
        duplicated = _valid_option(option_id="dup", value="value_a")
        with pytest.raises(ValueError, match="duplicate"):
            QuestionTemplate(
                id="primary_runtime_input",
                question_sv="Fråga?",
                question_en="Question?",
                help_sv="Hjälp",
                help_en="Help",
                options=(
                    duplicated,
                    _valid_option(option_id="dup", value="value_b"),
                ),
                worked_examples_sv=("Exempel",),
                worked_examples_en=("Example",),
                family="input_shape",
                priority_base=20,
                impact="architecture",
            )

    def test_template_rejects_negative_priority_base(self) -> None:
        with pytest.raises(ValueError, match="priority_base"):
            _valid_template(priority_base=-1)


class TestCatalogInvariants:
    def test_catalog_version_is_one(self) -> None:
        assert QUESTION_CATALOG_VERSION == 1

    def test_catalog_is_immutable(self) -> None:
        """`QUESTION_CATALOG` must be a `MappingProxyType`; mutation at
        runtime fails. Same contract as FCM and Pattern Registry."""
        first_key = next(iter(QUESTION_CATALOG))
        with pytest.raises(TypeError):
            QUESTION_CATALOG["new_key"] = QUESTION_CATALOG[first_key]  # type: ignore[index]
        with pytest.raises(TypeError):
            del QUESTION_CATALOG[first_key]  # type: ignore[misc]

    def test_catalog_keys_equal_known_slot_names(self) -> None:
        """Exact-key pin. The catalog seeds one template per architectural
        slot — renaming or adding a slot in
        `ai_builder_slot_vocabulary.py` requires a matching catalog
        change in the same diff. The live frozenset is the single source
        of truth."""
        assert frozenset(QUESTION_CATALOG.keys()) == KNOWN_REQUIREMENT_SLOT_NAMES, (
            f"Catalog drift: keys "
            f"{sorted(QUESTION_CATALOG.keys())} != slot names "
            f"{sorted(KNOWN_REQUIREMENT_SLOT_NAMES)}"
        )

    def test_template_keys_match_template_ids(self) -> None:
        """Registry key must equal `template.id`. Drift means a consumer
        traversing `.values()` sees a different id than one traversing
        `.keys()`."""
        for key, template in QUESTION_CATALOG.items():
            assert key == template.id, (
                f"Catalog key {key!r} does not match template.id {template.id!r}"
            )

    def test_legal_slot_values_are_derived_from_catalog_options(self) -> None:
        for slot_name, template in QUESTION_CATALOG.items():
            assert legal_slot_values(slot_name) == frozenset(
                option.value for option in template.options
            )

    def test_primary_runtime_input_exposes_json_as_legal_source_material(self) -> None:
        values = legal_slot_values("primary_runtime_input")
        rendered = render_question("primary_runtime_input", "sv")

        assert "json" in values
        assert "json" in {option.value for option in rendered.options}

    def test_legal_slot_values_fails_loudly_for_unknown_slot(self) -> None:
        with pytest.raises(KeyError):
            legal_slot_values("unknown_slot")

    def test_legacy_question_id_bridge_is_explicit_for_slot_renames(self) -> None:
        assert legacy_question_id_for_slot("primary_runtime_input") == (
            "input_material_mode"
        )
        assert legacy_question_id_for_slot("terminal_output") == "final_output_mode"
        assert legacy_question_id_for_slot("document_material_scope") == (
            "document_material_scope"
        )
        assert slot_name_for_legacy_question_id("input_material_mode") == (
            "primary_runtime_input"
        )
        assert slot_name_for_legacy_question_id("final_output_mode") == (
            "terminal_output"
        )


class TestCatalogStaticDiscoveryMetadata:
    def test_every_template_declares_static_discovery_metadata(self) -> None:
        families = frozenset(get_args(DiscoveryFamily))
        impacts = frozenset(get_args(DiscoveryImpact))

        for template in QUESTION_CATALOG.values():
            assert template.family in families, (
                f"{template.id}: unknown discovery family {template.family!r}"
            )
            assert template.priority_base >= 0, (
                f"{template.id}: priority_base must be non-negative"
            )
            assert template.impact in impacts, (
                f"{template.id}: unknown discovery impact {template.impact!r}"
            )

    def test_slot_issue_metadata_is_derived_from_catalog(self) -> None:
        for slot_name, template in QUESTION_CATALOG.items():
            issue_id = legacy_question_id_for_slot(slot_name)
            assert QUESTION_FAMILY[issue_id] == template.family
            assert DISCOVERY_ISSUE_PRIORITY[issue_id] == template.priority_base
            assert _QUESTION_IMPACT[issue_id] == template.impact

    def test_priority_map_separates_slot_and_non_slot_issue_ids(self) -> None:
        expected_issue_ids = _SLOT_DERIVED_ISSUE_IDS | _NON_SLOT_PRIORITY_ISSUE_IDS

        assert frozenset(DISCOVERY_ISSUE_PRIORITY) == expected_issue_ids

    def test_family_map_separates_slot_and_non_slot_issue_ids(self) -> None:
        expected_issue_ids = _SLOT_DERIVED_ISSUE_IDS | _NON_SLOT_FAMILY_ISSUE_IDS

        assert frozenset(QUESTION_FAMILY) == expected_issue_ids

    def test_impact_map_separates_slot_and_non_slot_issue_ids(self) -> None:
        expected_issue_ids = _SLOT_DERIVED_ISSUE_IDS | _NON_SLOT_IMPACT_ISSUE_IDS

        assert frozenset(_QUESTION_IMPACT) == expected_issue_ids


class TestBilingualContract:
    @pytest.fixture
    def all_templates(self) -> list[QuestionTemplate]:
        return list(QUESTION_CATALOG.values())

    def test_every_template_has_bilingual_question(
        self, all_templates: list[QuestionTemplate]
    ) -> None:
        for template in all_templates:
            assert template.question_sv.strip(), f"{template.id}: empty question_sv"
            assert template.question_en.strip(), f"{template.id}: empty question_en"

    def test_every_template_has_bilingual_help(
        self, all_templates: list[QuestionTemplate]
    ) -> None:
        for template in all_templates:
            assert template.help_sv.strip(), f"{template.id}: empty help_sv"
            assert template.help_en.strip(), f"{template.id}: empty help_en"

    def test_every_template_has_worked_examples_in_both_languages(
        self, all_templates: list[QuestionTemplate]
    ) -> None:
        for template in all_templates:
            assert len(template.worked_examples_sv) >= 1, (
                f"{template.id}: missing Swedish worked examples"
            )
            assert len(template.worked_examples_en) >= 1, (
                f"{template.id}: missing English worked examples"
            )
            for example in template.worked_examples_sv:
                assert example.strip(), (
                    f"{template.id}: empty string in worked_examples_sv"
                )
            for example in template.worked_examples_en:
                assert example.strip(), (
                    f"{template.id}: empty string in worked_examples_en"
                )

    def test_every_option_has_bilingual_copy(
        self, all_templates: list[QuestionTemplate]
    ) -> None:
        for template in all_templates:
            for option in template.options:
                assert option.label_sv.strip(), (
                    f"{template.id}:{option.id}: empty label_sv"
                )
                assert option.label_en.strip(), (
                    f"{template.id}:{option.id}: empty label_en"
                )
                assert option.description_sv.strip(), (
                    f"{template.id}:{option.id}: empty description_sv"
                )
                assert option.description_en.strip(), (
                    f"{template.id}:{option.id}: empty description_en"
                )


class TestQuestionExposure:
    """Every `QuestionTemplate` must declare whether the question surfaces
    as a user-visible requirement or stays internal to the planner. The
    Pattern Registry and discovery decision engine read this field to
    decide which questions the UI renders — the legacy
    ``DiscoveryQuestionSuggestion`` copies it today via
    ``question_exposure_for_id`` but only one source of truth should
    own the mapping.
    """

    def test_every_template_has_declared_exposure(self) -> None:
        for template in QUESTION_CATALOG.values():
            assert template.exposure in {"user_requirement", "planner_internal"}, (
                f"{template.id}: exposure must be user_requirement or "
                f"planner_internal, got {template.exposure!r}"
            )

    def test_structured_analysis_need_is_planner_internal(self) -> None:
        template = QUESTION_CATALOG["structured_analysis_need"]
        assert template.exposure == "planner_internal", (
            "structured_analysis_need is a planner-internal follow-up; "
            "it must not surface as a user-visible requirement"
        )

    def test_user_facing_slots_default_to_user_requirement(self) -> None:
        user_facing_slots = KNOWN_REQUIREMENT_SLOT_NAMES - {"structured_analysis_need"}
        for slot in user_facing_slots:
            template = QUESTION_CATALOG[slot]
            assert template.exposure == "user_requirement", (
                f"{slot}: expected user_requirement exposure, got {template.exposure!r}"
            )


class TestPatternRegistryBackfill:
    """Pattern Registry's `question_template_ids` field forward-references
    this catalog. The dangling-reference CI test below guards any
    Pattern-Registry / Question-Catalog change that would leave a
    reference unresolved.
    """

    def test_every_positive_pattern_has_question_template_ids(self) -> None:
        for pattern in PATTERN_REGISTRY.values():
            if pattern.polarity != "positive":
                continue
            assert len(pattern.question_template_ids) >= 1, (
                f"{pattern.id}: positive pattern must declare >=1 question_template_id"
            )

    def test_question_template_ids_are_an_order_preserving_unique_subset_of_slots(
        self,
    ) -> None:
        """Durable coupling: every question surfaced for a pattern must
        correspond to an architectural slot the pattern actually cares
        about. The current seeds happen to set them equal, but the
        contract is order-preserving unique subset — a future pattern may
        legitimately resolve a slot through inference (profile,
        deterministic signal) without surfacing the canonical question.
        The inverse — a `question_template_id` that doesn't map to any
        declared slot, or a duplicate, or one that follows a different
        order than its slot — would surface the same question twice or
        ask the user out of sequence; reject at contract level."""
        for pattern in PATTERN_REGISTRY.values():
            if pattern.polarity != "positive":
                continue
            qids = pattern.question_template_ids
            slots = pattern.required_architectural_slots
            assert len(set(qids)) == len(qids), (
                f"{pattern.id}: duplicate question_template_id in {qids}"
            )
            slot_set = set(slots)
            extras = [qid for qid in qids if qid not in slot_set]
            assert not extras, (
                f"{pattern.id}: question_template_ids {extras} have no "
                f"corresponding architectural slot on this pattern "
                f"(slots: {list(slots)})"
            )
            slot_index = {slot: position for position, slot in enumerate(slots)}
            qid_positions = [slot_index[qid] for qid in qids]
            assert qid_positions == sorted(qid_positions), (
                f"{pattern.id}: question_template_ids {list(qids)} are "
                f"reordered relative to required_architectural_slots "
                f"{list(slots)}; use slot order"
            )

    def test_every_question_template_id_resolves_in_catalog(self) -> None:
        """Dangling-reference CI guard.

        Every entry in any ``Pattern.question_template_ids`` tuple must
        resolve to a live ``QUESTION_CATALOG`` row. Any future Pattern
        Registry or Question Catalog change that introduces a dangling
        reference must fail here before landing.

        This is a data-reference rule, not an import rule; it lives with
        the Question Catalog data contract rather than with the
        importlinter boundary tests.
        """
        for pattern in PATTERN_REGISTRY.values():
            for qid in pattern.question_template_ids:
                assert qid in QUESTION_CATALOG, (
                    f"{pattern.id}: question_template_id {qid!r} does not "
                    f"resolve in QUESTION_CATALOG; available keys: "
                    f"{sorted(QUESTION_CATALOG.keys())}"
                )

    def test_negative_patterns_keep_empty_question_template_ids(self) -> None:
        """Negative patterns describe shapes to AVOID, not user questions
        to surface. Their `question_template_ids` must stay empty — the
        planner never asks 'would you like the banned shape?'."""
        for pattern in PATTERN_REGISTRY.values():
            if pattern.polarity != "negative":
                continue
            assert pattern.question_template_ids == (), (
                f"{pattern.id}: negative pattern has non-empty "
                f"question_template_ids {pattern.question_template_ids}"
            )


class TestQuestionCatalogPublicApi:
    """Public UX/i18n entry points: locale-resolved rendering and
    slot → id lookup.
    """

    def test_render_question_in_swedish_projects_sv_fields(self) -> None:
        """Locale 'sv' snapshots the Swedish question, help, worked
        examples, and each option's Swedish label/description."""
        rendered = render_question("primary_runtime_input", "sv")
        assert isinstance(rendered, RenderedQuestion)
        assert rendered.id == "primary_runtime_input"
        assert rendered.locale == "sv"
        assert rendered.question.startswith("Vilket material")
        assert rendered.help.startswith("Ett flöde")
        assert rendered.worked_examples, "expected non-empty worked examples"
        assert all(isinstance(opt, RenderedOption) for opt in rendered.options)
        first_option = rendered.options[0]
        assert first_option.label == "Ljud"
        assert first_option.description.startswith("Ladda upp")
        assert first_option.value == "audio"

    def test_render_question_in_english_projects_en_fields(self) -> None:
        """Locale 'en' snapshots the English fields symmetrically."""
        rendered = render_question("primary_runtime_input", "en")
        assert rendered.locale == "en"
        assert rendered.question.startswith("What source material")
        assert rendered.help.startswith("A flow has")
        first_option = rendered.options[0]
        assert first_option.label == "Audio"
        assert first_option.description.startswith("Upload an audio")
        assert first_option.value == "audio"

    def test_render_question_preserves_option_order(self) -> None:
        """Option order is part of the UX contract — the catalog author
        ordered options deliberately (e.g. audio, documents, text). The
        projection must not reorder them."""
        template = QUESTION_CATALOG["primary_runtime_input"]
        rendered = render_question("primary_runtime_input", "sv")
        source_ids = tuple(opt.id for opt in template.options)
        rendered_ids = tuple(opt.id for opt in rendered.options)
        assert rendered_ids == source_ids

    def test_render_question_raises_key_error_for_unknown_id(self) -> None:
        """A typo in `template_id` is programmer error; failing loudly
        surfaces it instead of returning an empty projection."""
        with pytest.raises(KeyError):
            render_question("no_such_template", "sv")

    def test_render_question_raises_value_error_for_unsupported_locale(
        self,
    ) -> None:
        """Lax callers that slip a non-Literal through at runtime must
        fail loudly rather than silently rendering English. A silent
        fallback would mask locale-propagation bugs at the UI boundary."""
        with pytest.raises(ValueError, match="Unsupported locale"):
            render_question("terminal_output", "de")  # type: ignore[arg-type]

    def test_render_question_returns_frozen_dataclass(self) -> None:
        """The snapshot is read-only. A caller that patches fields in
        place between render and display would cause UI/server drift."""
        rendered = render_question("terminal_output", "sv")
        with pytest.raises(FrozenInstanceError):
            rendered.question = "mutated"  # type: ignore[misc]

    def test_render_question_matches_source_worked_examples_by_locale(
        self,
    ) -> None:
        """Worked examples must come from the same locale as the
        question/help copy — a mixed-locale render would confuse the
        user."""
        template = QUESTION_CATALOG["terminal_output"]
        sv = render_question("terminal_output", "sv")
        en = render_question("terminal_output", "en")
        assert sv.worked_examples == template.worked_examples_sv
        assert en.worked_examples == template.worked_examples_en

    def test_question_ids_for_slot_returns_id_tuple_when_slot_has_template(
        self,
    ) -> None:
        """Current catalog shape is one template per slot; the returned
        tuple has exactly one entry for every seeded slot."""
        ids = question_ids_for_slot("primary_runtime_input")
        assert ids == ("primary_runtime_input",)

    def test_question_ids_for_slot_returns_empty_for_unknown_slot(
        self,
    ) -> None:
        """Unknown slot → empty tuple. Callers use this as the
        'is there copy for this slot?' read, so raising would force
        every caller to wrap with try/except."""
        assert question_ids_for_slot("no_such_slot") == ()

    def test_question_ids_for_slot_covers_every_known_slot(self) -> None:
        """Contract: every slot name in the live vocabulary resolves to
        at least one id today. Catches drift if a future catalog change
        drops a template but leaves the slot in the vocabulary."""
        for slot in KNOWN_REQUIREMENT_SLOT_NAMES:
            ids = question_ids_for_slot(slot)
            assert ids, f"slot {slot!r} has no question ids in the catalog"


class TestDomainNeutrality:
    """Default-surface neutrality for the `QUESTION_CATALOG` render.

    AI Builder supports specialty flows — decision-support memos,
    tjänsteskrivelse drafting, remiss processing — alongside
    procurement, onboarding, transcription, extraction, comparison, and
    template fill. Specialty vocabulary is welcome in recognizer tuples,
    knowledge-pack sections keyed on a scenario, and benchmark cases.
    What must not happen is specialty framing leaking into the default
    template render, because the catalog's seed questions reach every
    user before scenario is known.

    A catalog edit that surfaces specialty framing in the default
    rendering must fail here before landing. Generic business terms
    (`juridiska risker`, `ekonomiska konsekvenser`, `guldexempel`, etc.)
    are NOT banned — those serve every domain.
    """

    _BANNED_DEFAULT_RENDER_TOKENS: tuple[str, ...] = (
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
        "ärendedokument",
        "ärendeunderlag",
        "kommunala handlingar",
        "huvudärende",
        "ärendepaket",
        "ärendeintag",
        "ärendesammanfattning",
        "ärende åt gången",
        "diarienummer",
        "case number",
    )

    def test_no_specialty_framing_in_default_template_render(self) -> None:
        for template_id in QUESTION_CATALOG:
            for locale in ("sv", "en"):
                rendered = render_question(template_id, locale)  # type: ignore[arg-type]
                blob_parts = [
                    rendered.question,
                    rendered.help,
                    *rendered.worked_examples,
                ]
                for option in rendered.options:
                    blob_parts.append(option.label)
                    blob_parts.append(option.description)
                lowered = "\n".join(blob_parts).casefold()
                for token in self._BANNED_DEFAULT_RENDER_TOKENS:
                    assert token.casefold() not in lowered, (
                        f"{template_id} [{locale}]: specialty framing "
                        f"token {token!r} leaked into default rendered output"
                    )


class TestQuestionCopyParity:
    """The `QUESTION_CATALOG` and `ai_builder_discovery_questions` each
    render the same user-facing question surface. Both are live — the
    catalog feeds the create-mode knowledge pack, the builders feed the
    discovery runtime. Any drift between them means the planner and the
    runtime disagree on what to call the same slot. Pin exact parity
    per (template_id, locale) across question text, help text, options,
    and worked examples so a future edit to one source blows up here
    before shipping.
    """

    @staticmethod
    def _builders_by_template_id():
        from intric.flows.ai_builder.ai_builder_discovery_questions import (
            comparison_scope_question,
            document_kind_question,
            document_material_scope_question,
            docx_output_mode_question,
            final_output_mode_question,
            final_output_scope_question,
            final_pdf_type_question,
            flow_input_architecture_question,
            input_material_mode_question,
            output_reader_question,
            pdf_generation_mode_question,
            post_processing_goal_question,
            processing_scope_question,
            runtime_metadata_fields_question,
            structured_analysis_need_question,
            structured_io_contract_question,
        )

        return {
            "processing_scope": processing_scope_question,
            "input_material_mode": input_material_mode_question,
            "flow_input_architecture": flow_input_architecture_question,
            "document_kind": document_kind_question,
            "document_material_scope": document_material_scope_question,
            "post_processing_goal": post_processing_goal_question,
            "structured_io_contract": structured_io_contract_question,
            "comparison_scope": comparison_scope_question,
            "final_output_mode": final_output_mode_question,
            "docx_output_mode": docx_output_mode_question,
            "output_reader": output_reader_question,
            "final_output_scope": final_output_scope_question,
            "runtime_metadata_fields": runtime_metadata_fields_question,
            "structured_analysis_need": structured_analysis_need_question,
            "final_pdf_type": final_pdf_type_question,
            "pdf_generation_mode": pdf_generation_mode_question,
        }

    @pytest.mark.parametrize("locale", ["sv", "en"])
    def test_catalog_matches_discovery_builder_surface(self, locale: str) -> None:
        builders = self._builders_by_template_id()
        for template_id, builder in builders.items():
            if template_id not in QUESTION_CATALOG:
                continue
            rendered = render_question(template_id, locale)  # type: ignore[arg-type]
            suggestion = builder(locale)  # type: ignore[arg-type]
            assert rendered.question == suggestion.question, (
                f"{template_id} [{locale}]: question text diverged "
                f"between catalog and discovery builder"
            )
            catalog_options = {option.id: option for option in rendered.options}
            builder_options = {option.id: option for option in suggestion.options}
            assert set(catalog_options) == set(builder_options), (
                f"{template_id} [{locale}]: option id set diverged "
                f"between catalog and discovery builder"
            )
            for option_id, catalog_option in catalog_options.items():
                builder_option = builder_options[option_id]
                assert catalog_option.label == builder_option.label, (
                    f"{template_id} [{locale}] option {option_id!r}: "
                    f"label diverged between catalog and discovery builder"
                )
                assert catalog_option.description == builder_option.description, (
                    f"{template_id} [{locale}] option {option_id!r}: "
                    f"description diverged between catalog and discovery "
                    f"builder"
                )
                assert catalog_option.value == builder_option.value, (
                    f"{template_id} [{locale}] option {option_id!r}: "
                    f"value diverged between catalog and discovery builder"
                )
