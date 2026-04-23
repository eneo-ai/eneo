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

import pytest

from intric.flows.ai_builder.ai_builder_slot_vocabulary import (
    KNOWN_REQUIREMENT_SLOT_NAMES,
)
from intric.flows.ai_builder.pattern_registry import PATTERN_REGISTRY
from intric.flows.ai_builder.question_catalog import (
    QUESTION_CATALOG,
    QUESTION_CATALOG_VERSION,
    QuestionOption,
    QuestionTemplate,
    RenderedOption,
    RenderedQuestion,
    question_ids_for_slot,
    render_question,
)


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
            )


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
    """AI Builder is general-purpose: it builds procurement, onboarding,
    transcription, extraction, comparison, and template-fill flows — not
    just decision-support flows. Swedish case-management vocabulary AND
    the English `decision support` compound must not appear in any
    rendered question, label, description, help copy, or worked example.

    The banned-token list mirrors the domain-neutrality rule in the
    Golden Coverage Matrix. A catalog change that reintroduces any of
    these tokens fails here before landing.
    """

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

    def test_no_banned_tokens_in_any_rendered_template(self) -> None:
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
                for token in self._BANNED_SPECIALTY_TOKENS:
                    assert token.casefold() not in lowered, (
                        f"{template_id} [{locale}]: banned specialty "
                        f"token {token!r} found in rendered output"
                    )
