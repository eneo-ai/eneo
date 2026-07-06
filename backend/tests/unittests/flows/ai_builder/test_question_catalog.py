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

from eneo.flows.ai_builder.ai_builder_discovery_decision_engine import (
    _QUESTION_IMPACT,
)
from eneo.flows.ai_builder.ai_builder_discovery_families import QUESTION_FAMILY
from eneo.flows.ai_builder.ai_builder_discovery_models import DiscoveryLanguage
from eneo.flows.ai_builder.ai_builder_discovery_priority import (
    DISCOVERY_ISSUE_PRIORITY,
)
from eneo.flows.ai_builder.ai_builder_slot_vocabulary import (
    KNOWN_REQUIREMENT_SLOT_NAMES,
    DiscoveryFamily,
    DiscoveryImpact,
)
from eneo.flows.ai_builder.pattern_registry import PATTERN_REGISTRY
from eneo.flows.ai_builder.question_catalog import (
    QUESTION_CATALOG,
    QuestionOption,
    QuestionTemplate,
    RenderedOption,
    RenderedQuestion,
    legal_slot_values,
    render_question,
)

_SLOT_DERIVED_ISSUE_IDS = KNOWN_REQUIREMENT_SLOT_NAMES

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

    def test_slot_backed_question_ids_are_catalog_slot_names(self) -> None:
        question_ids = frozenset(QUESTION_CATALOG)

        assert question_ids == KNOWN_REQUIREMENT_SLOT_NAMES
        assert "primary_runtime_input" in question_ids
        assert "terminal_output" in question_ids
        assert "flow_input_architecture" not in question_ids
        assert "final_pdf_type" not in question_ids


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
            assert QUESTION_FAMILY[slot_name] == template.family
            assert DISCOVERY_ISSUE_PRIORITY[slot_name] == template.priority_base
            assert _QUESTION_IMPACT[slot_name] == template.impact

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

    def test_user_facing_slots_default_to_user_requirement(self) -> None:
        for slot in KNOWN_REQUIREMENT_SLOT_NAMES:
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


_SLOT_BACKED_DISCOVERY_GOLDEN = {
    ("primary_runtime_input", "sv"): {
        "question_id": "primary_runtime_input",
        "question": "Vilket material ska flödet ta emot vid körning?",
        "options": (
            (
                "audio",
                "Ljud",
                "Ladda upp en ljudfil som ska transkriberas i flödet.",
                "audio",
            ),
            (
                "documents",
                "Dokument",
                "Ladda upp dokument som PDF, Word eller liknande filer.",
                "documents",
            ),
            (
                "json",
                "JSON",
                "Ta emot en strukturerad JSON-payload vid körning.",
                "json",
            ),
            ("text", "Text", "Klistra in materialet direkt som text.", "text"),
            (
                "text_and_documents",
                "Både text och dokument",
                "Stöd både inklistrad text och uppladdade dokument.",
                "text_and_documents",
            ),
        ),
        "selection_mode": "single",
        "allow_custom": True,
        "exposure": "user_requirement",
    },
    ("primary_runtime_input", "en"): {
        "question_id": "primary_runtime_input",
        "question": "What source material should the flow accept at runtime?",
        "options": (
            (
                "audio",
                "Audio",
                "Upload an audio file that should be transcribed in the flow.",
                "audio",
            ),
            (
                "documents",
                "Documents",
                "Upload documents such as PDF or Word files.",
                "documents",
            ),
            ("json", "JSON", "Accept a structured JSON payload at runtime.", "json"),
            ("text", "Text", "Paste the source material as text.", "text"),
            (
                "text_and_documents",
                "Both text and documents",
                "Support both pasted text and uploaded documents.",
                "text_and_documents",
            ),
        ),
        "selection_mode": "single",
        "allow_custom": True,
        "exposure": "user_requirement",
    },
    ("terminal_output", "sv"): {
        "question_id": "terminal_output",
        "question": "Vad ska flödet producera som slutresultat?",
        "options": (
            (
                "structured_text",
                "Strukturerat textresultat",
                "Ett läsbart memo, rapport eller sammanfattning direkt i flödet.",
                "structured_text",
            ),
            (
                "pdf_document",
                "PDF-dokument",
                "Generera en PDF som slutresultat.",
                "pdf_document",
            ),
            (
                "docx_document",
                "DOCX-dokument",
                "Generera ett Word-dokument som slutresultat.",
                "docx_document",
            ),
            (
                "structured_json",
                "Strukturerad JSON",
                "Maskinläsbara fält för vidare automation eller system.",
                "structured_json",
            ),
        ),
        "selection_mode": "single",
        "allow_custom": True,
        "exposure": "user_requirement",
    },
    ("terminal_output", "en"): {
        "question_id": "terminal_output",
        "question": "What should the flow produce as the final output?",
        "options": (
            (
                "structured_text",
                "Structured text output",
                "A readable memo, report, or summary in the flow output.",
                "structured_text",
            ),
            (
                "pdf_document",
                "PDF document",
                "Generate a PDF document as the final output.",
                "pdf_document",
            ),
            (
                "docx_document",
                "DOCX document",
                "Generate a Word document as the final output.",
                "docx_document",
            ),
            (
                "structured_json",
                "Structured JSON",
                "Produce machine-readable fields for downstream systems.",
                "structured_json",
            ),
        ),
        "selection_mode": "single",
        "allow_custom": True,
        "exposure": "user_requirement",
    },
    ("docx_output_mode", "sv"): {
        "question_id": "docx_output_mode",
        "question": "Hur ska DOCX-resultatet skapas?",
        "options": (
            (
                "generated_docx",
                "Genererad DOCX utan mall",
                "Skapa dokumentinnehållet direkt utan en fast mall.",
                "generated_docx",
            ),
            (
                "template_fill_docx",
                "DOCX från mall",
                "Fyll en befintlig DOCX-mall med strukturerade fält.",
                "template_fill_docx",
            ),
        ),
        "selection_mode": "single",
        "allow_custom": True,
        "exposure": "user_requirement",
    },
    ("docx_output_mode", "en"): {
        "question_id": "docx_output_mode",
        "question": "How should the DOCX output be created?",
        "options": (
            (
                "generated_docx",
                "Generated DOCX without template",
                "Generate the document content directly without a fixed template.",
                "generated_docx",
            ),
            (
                "template_fill_docx",
                "DOCX from template",
                "Fill an existing DOCX template with structured fields.",
                "template_fill_docx",
            ),
        ),
        "selection_mode": "single",
        "allow_custom": True,
        "exposure": "user_requirement",
    },
    ("pdf_generation_mode", "sv"): {
        "question_id": "pdf_generation_mode",
        "question": "När du säger PDF-mall, vilket upplägg menar du?",
        "options": (
            (
                "generated_pdf",
                "Vanlig genererad PDF",
                "Skapa en PDF direkt från analysen utan en fast mall.",
                "generated_pdf",
            ),
            (
                "pdf_template_requested",
                "Specifik PDF-mall krävs",
                "Slutresultatet behöver följa en bestämd PDF-mall eller layout. "
                "Inbyggd mallfyllning stöds bara för DOCX/Word.",
                "pdf_template_requested",
            ),
        ),
        "selection_mode": "single",
        "allow_custom": True,
        "exposure": "user_requirement",
    },
    ("pdf_generation_mode", "en"): {
        "question_id": "pdf_generation_mode",
        "question": "When you say PDF template, which setup do you mean?",
        "options": (
            (
                "generated_pdf",
                "Normal generated PDF",
                "Generate a PDF directly from the analysis without a fixed template.",
                "generated_pdf",
            ),
            (
                "pdf_template_requested",
                "A specific PDF template is required",
                "The final result must follow a specific PDF template or layout. "
                "Native template filling is only supported for DOCX/Word.",
                "pdf_template_requested",
            ),
        ),
        "selection_mode": "single",
        "allow_custom": True,
        "exposure": "user_requirement",
    },
    ("document_material_scope", "sv"): {
        "question_id": "document_material_scope",
        "question": "Hur brukar underlaget per körning se ut?",
        "options": (
            (
                "single_document_case",
                "Ett huvuddokument per körning",
                "Varje körning analyserar normalt ett primärt dokument.",
                "single_document_case",
            ),
            (
                "multiple_documents_case",
                "Flera dokument i samma körning",
                "Varje körning ska kunna hantera ett dokumentpaket med flera relaterade filer.",
                "multiple_documents_case",
            ),
            (
                "flexible_document_case",
                "Ibland ett, ibland flera dokument",
                "Flödet ska fungera både för en enskild fil och ett dokumentpaket.",
                "flexible_document_case",
            ),
        ),
        "selection_mode": "single",
        "allow_custom": True,
        "exposure": "user_requirement",
    },
    ("document_material_scope", "en"): {
        "question_id": "document_material_scope",
        "question": "For one run, what should the uploaded source material usually look like?",
        "options": (
            (
                "single_document_case",
                "One main document per run",
                "Each run usually analyzes one primary PDF or document.",
                "single_document_case",
            ),
            (
                "multiple_documents_case",
                "Several documents in the same run",
                "Each run should handle a document package with multiple related files.",
                "multiple_documents_case",
            ),
            (
                "flexible_document_case",
                "Either one or several documents",
                "The flow should work for both a single file and a document package.",
                "flexible_document_case",
            ),
        ),
        "selection_mode": "single",
        "allow_custom": True,
        "exposure": "user_requirement",
    },
    ("post_processing_goal", "sv"): {
        "question_id": "post_processing_goal",
        "question": "Vad ska flödet hjälpa dig göra med materialet?",
        "options": (
            (
                "stop_after_primary_operation",
                "Bara grundresultatet",
                "Stanna efter exempelvis transkription eller konvertering.",
                "stop_after_primary_operation",
            ),
            (
                "summarize_or_overview",
                "Sammanfatta eller ge överblick",
                "Skapa en kortare sammanfattning eller översikt.",
                "summarize_or_overview",
            ),
            (
                "extract_key_information",
                "Plocka ut nyckeluppgifter",
                "Hämta ut viktiga fakta, fält, datum, belopp eller liknande.",
                "extract_key_information",
            ),
            (
                "structure_key_information",
                "Strukturera materialet",
                "Gör materialet till tydliga anteckningar, memo eller rapport.",
                "structure_key_information",
            ),
            (
                "action_followup",
                "Beslut, nästa steg och uppföljning",
                "Plocka ut beslut, åtgärder, ansvariga, deadlines och öppna frågor.",
                "action_followup",
            ),
            (
                "decision_support",
                "Rekommendationer och vägval",
                "Ta fram rekommendationer eller nästa möjliga vägval.",
                "decision_support",
            ),
            (
                "risk_or_issue_review",
                "Granska risker eller problem",
                "Identifiera risker, avvikelser, osäkerheter eller problem.",
                "risk_or_issue_review",
            ),
            (
                "compare_or_validate",
                "Jämföra eller validera",
                "Jämför mot annat underlag, regler, schema eller checklista.",
                "compare_or_validate",
            ),
        ),
        "selection_mode": "single",
        "allow_custom": True,
        "exposure": "user_requirement",
    },
    ("post_processing_goal", "en"): {
        "question_id": "post_processing_goal",
        "question": "What should the flow help you do with the material?",
        "options": (
            (
                "stop_after_primary_operation",
                "Only the primary result",
                "Stop after the transcript, conversion, or other primary result.",
                "stop_after_primary_operation",
            ),
            (
                "summarize_or_overview",
                "Summarize or give an overview",
                "Create a shorter summary or overview.",
                "summarize_or_overview",
            ),
            (
                "extract_key_information",
                "Extract key information",
                "Extract important facts, fields, dates, amounts, or similar details.",
                "extract_key_information",
            ),
            (
                "structure_key_information",
                "Structure the material",
                "Turn the material into clear notes, a memo, or a report.",
                "structure_key_information",
            ),
            (
                "action_followup",
                "Decisions, next steps, and follow-up",
                "Extract decisions, actions, owners, deadlines, and open questions.",
                "action_followup",
            ),
            (
                "decision_support",
                "Recommendations and guidance",
                "Create recommendations or next possible choices.",
                "decision_support",
            ),
            (
                "risk_or_issue_review",
                "Review risks or issues",
                "Identify risks, deviations, uncertainty, or problems.",
                "risk_or_issue_review",
            ),
            (
                "compare_or_validate",
                "Compare or validate",
                "Compare against other material, rules, a schema, or a checklist.",
                "compare_or_validate",
            ),
        ),
        "selection_mode": "single",
        "allow_custom": True,
        "exposure": "user_requirement",
    },
    ("structured_io_contract", "sv"): {
        "question_id": "structured_io_contract",
        "question": "Vad ska flödet göra mellan input-JSON och output-JSON?",
        "options": (
            (
                "map_to_new_schema",
                "Mappa till nytt schema",
                "Välj, döp om eller flytta fält till en ny JSON-struktur.",
                "map_to_new_schema",
            ),
            (
                "validate_against_schema_or_rules",
                "Validera mot schema eller regler",
                "Kontrollera payloaden mot ett schema, regler eller krav.",
                "validate_against_schema_or_rules",
            ),
            (
                "extract_or_compute_fields",
                "Extrahera eller beräkna fält",
                "Plocka ut, kombinera eller beräkna värden i JSON.",
                "extract_or_compute_fields",
            ),
            (
                "normalize_or_enrich",
                "Normalisera eller berika",
                "Städa, standardisera eller komplettera payloaden.",
                "normalize_or_enrich",
            ),
            (
                "classify_or_tag",
                "Klassificera eller tagga",
                "Lägg till kategori, status, etiketter eller routingfält.",
                "classify_or_tag",
            ),
            (
                "custom_schema_or_rules",
                "Eget schema eller egna regler",
                "Följ ett särskilt kontrakt som användaren beskriver.",
                "custom_schema_or_rules",
            ),
        ),
        "selection_mode": "single",
        "allow_custom": True,
        "exposure": "user_requirement",
    },
    ("structured_io_contract", "en"): {
        "question_id": "structured_io_contract",
        "question": "What should the flow do between input JSON and output JSON?",
        "options": (
            (
                "map_to_new_schema",
                "Map to a new schema",
                "Select, rename, or move fields into a new JSON shape.",
                "map_to_new_schema",
            ),
            (
                "validate_against_schema_or_rules",
                "Validate against schema or rules",
                "Check the payload against a schema, rules, or requirements.",
                "validate_against_schema_or_rules",
            ),
            (
                "extract_or_compute_fields",
                "Extract or compute fields",
                "Extract, combine, or compute values in JSON.",
                "extract_or_compute_fields",
            ),
            (
                "normalize_or_enrich",
                "Normalize or enrich",
                "Clean, standardize, or enrich the payload.",
                "normalize_or_enrich",
            ),
            (
                "classify_or_tag",
                "Classify or tag",
                "Add category, status, labels, or routing fields.",
                "classify_or_tag",
            ),
            (
                "custom_schema_or_rules",
                "Custom schema or rules",
                "Follow a specific contract described by the user.",
                "custom_schema_or_rules",
            ),
        ),
        "selection_mode": "single",
        "allow_custom": True,
        "exposure": "user_requirement",
    },
    ("runtime_metadata_fields", "sv"): {
        "question_id": "runtime_metadata_fields",
        "question": "Ska användaren också ange metadata vid körning?",
        "options": (
            (
                "no_extra_metadata",
                "Inga extra fält",
                "Använd bara de uppladdade dokumenten som indata.",
                "no_extra_metadata",
            ),
            (
                "basic_case_metadata",
                "Lägg till grundläggande metadata",
                "Låt användaren ange några enkla återanvändbara fält.",
                "basic_case_metadata",
            ),
            (
                "detailed_case_metadata",
                "Lägg till rikare metadatafält",
                "Samla flera återanvändbara fält som referenser, språk, fokus, "
                "datum eller ansvarig avdelning.",
                "detailed_case_metadata",
            ),
        ),
        "selection_mode": "single",
        "allow_custom": True,
        "exposure": "user_requirement",
    },
    ("runtime_metadata_fields", "en"): {
        "question_id": "runtime_metadata_fields",
        "question": "Should the user also enter metadata at runtime?",
        "options": (
            (
                "no_extra_metadata",
                "No extra fields",
                "Use only the uploaded documents as input.",
                "no_extra_metadata",
            ),
            (
                "basic_case_metadata",
                "Add basic metadata",
                "Let the user enter a few simple reusable fields.",
                "basic_case_metadata",
            ),
            (
                "detailed_case_metadata",
                "Add richer metadata fields",
                "Collect several reusable inputs such as references, language, focus, "
                "dates, or responsible department.",
                "detailed_case_metadata",
            ),
        ),
        "selection_mode": "single",
        "allow_custom": True,
        "exposure": "user_requirement",
    },
}


def _discovery_payload(
    question_id: str,
    locale: DiscoveryLanguage,
) -> dict[str, object]:
    from eneo.flows.ai_builder.ai_builder_discovery_questions import (
        question_suggestion_for_id,
    )

    suggestion = question_suggestion_for_id(question_id, language=locale)
    assert suggestion is not None
    return {
        "question_id": suggestion.question_id,
        "question": suggestion.question,
        "options": tuple(
            (option.id, option.label, option.description, option.value)
            for option in suggestion.options
        ),
        "selection_mode": suggestion.selection_mode,
        "allow_custom": suggestion.allow_custom,
        "exposure": suggestion.exposure,
    }


class TestSlotBackedDiscoveryQuestionProjection:
    @pytest.mark.parametrize(
        ("slot_name", "locale"),
        sorted(_SLOT_BACKED_DISCOVERY_GOLDEN),
    )
    def test_slot_backed_discovery_questions_match_frozen_payload(
        self,
        slot_name: str,
        locale: DiscoveryLanguage,
    ) -> None:
        assert (
            _discovery_payload(slot_name, locale)
            == (_SLOT_BACKED_DISCOVERY_GOLDEN[(slot_name, locale)])
        )

    def test_frozen_payload_covers_every_catalog_slot_and_locale(self) -> None:
        assert set(_SLOT_BACKED_DISCOVERY_GOLDEN) == {
            (slot_name, locale)
            for slot_name in QUESTION_CATALOG
            for locale in ("sv", "en")
        }

    @pytest.mark.parametrize("locale", ["sv", "en"])
    def test_product_specific_questions_are_not_catalog_slot_projections(
        self,
        locale: DiscoveryLanguage,
    ) -> None:
        input_projection = _discovery_payload("primary_runtime_input", locale)
        flow_architecture = _discovery_payload("flow_input_architecture", locale)
        terminal_projection = _discovery_payload("terminal_output", locale)
        final_pdf_type = _discovery_payload("final_pdf_type", locale)

        assert flow_architecture["question_id"] == "flow_input_architecture"
        assert flow_architecture["question"] != input_projection["question"]
        assert final_pdf_type["question_id"] == "final_pdf_type"
        assert final_pdf_type["question"] != terminal_projection["question"]

    @pytest.mark.parametrize("locale", ["sv", "en"])
    def test_external_delivery_keeps_own_text_and_final_output_options(
        self,
        locale: DiscoveryLanguage,
    ) -> None:
        from eneo.flows.ai_builder.ai_builder_discovery_questions import (
            external_delivery_internal_output_question,
        )

        suggestion = external_delivery_internal_output_question(locale)
        final_output = _discovery_payload("terminal_output", locale)

        assert suggestion.question != final_output["question"]
        assert suggestion.question_id == final_output["question_id"]
        assert (
            tuple(
                (option.id, option.label, option.description, option.value)
                for option in suggestion.options
            )
            == final_output["options"]
        )
        assert suggestion.selection_mode == final_output["selection_mode"]
        assert suggestion.allow_custom == final_output["allow_custom"]
        assert suggestion.exposure == final_output["exposure"]
