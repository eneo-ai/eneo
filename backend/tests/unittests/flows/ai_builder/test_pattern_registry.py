"""Pattern Registry tests.

Covers: `Pattern` dataclass shape (structural planner-strategy fields
only), registry immutability, version constant, exact seed ids,
slot-vocabulary anchored on the live `ai_builder_slot_vocabulary`
leaf export, and negative-pattern bite asserted against live FCM callables.
Matches the `test_ai_builder_recipe_selector.py` idiom — plain test
class, no fixtures beyond scoped helpers, direct imports.

User-facing copy (labels, localized text, help prose) is explicitly NOT
pinned here; that surface lives on the Question Catalog and is never
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
    find_pattern_candidates,
    question_template_ids_for_slot,
    render_knowledge_pack,
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

# Exact seed pinned here — the canonical archetype list lives in code,
# not in any external target band. Changing this set is a deliberate
# surface change and should be a one-line diff against both registry
# and test.
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
        "form_field_runtime_inputs",
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


def _extract_pattern_block(rendered: str, pattern_id: str) -> str:
    """Return the lines of `rendered` that belong to `pattern_id`'s
    per-pattern block.

    `render_knowledge_pack` emits one block per pattern: a `- <id>`
    header followed by indented `  <field>: ...` lines. The block ends
    at the next unindented line (either another pattern header or a
    section header). This helper lets a test assert content is
    *inside* a specific pattern's block rather than merely present
    somewhere in the pack.
    """
    header = f"- {pattern_id}"
    lines = rendered.splitlines()
    block_lines: list[str] = []
    in_block = False
    for line in lines:
        if line == header:
            in_block = True
            block_lines.append(line)
            continue
        if not in_block:
            continue
        if line.startswith("  ") or line == "":
            block_lines.append(line)
            continue
        break
    return "\n".join(block_lines)


# Map negative pattern id → live-FCM assertion the test must satisfy.
# A negative pattern added without a live assertion here fails
# `test_every_negative_has_live_fcm_assertion`, forcing the author to
# name the engine-truth anchor instead of shipping prose.
_NEGATIVE_FCM_ASSERTIONS: dict[str, Callable[[], None]] = {
    "image_input_pipeline": _assert_image_input_not_exposed,
    "template_fill_non_docx": _assert_template_fill_requires_docx,
}


class TestPatternDataclass:
    def test_pattern_version_is_four(self) -> None:
        assert PATTERN_REGISTRY_VERSION == 4

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
            retrieval_hints=(),
            negative_examples=(),
            required_architectural_slots=(),
            question_template_ids=(),
            polarity="positive",
        )
        assert pattern.chain_steps == ()

    def test_pattern_recipe_sections_defaults_to_empty_tuple(self) -> None:
        """`recipe_sections` names the knowledge-pack recipe-section keys
        (`"transcription"`, `"docx_template"`, etc.) that a pattern
        activates when it wins a `find_pattern_candidates` scoring pass.
        Patterns without a stable recipe-section mapping — including
        every negative pattern and patterns whose retrieval hints are
        too generic for score-based triggering — leave it empty; the
        default is `()` so adding the field does not require touching
        the existing negative-pattern seeds."""
        pattern = Pattern(
            id="fixture",
            examples=(),
            retrieval_hints=(),
            negative_examples=(),
            required_architectural_slots=(),
            question_template_ids=(),
            polarity="positive",
        )
        assert pattern.recipe_sections == ()


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
        must declare their step sequence in `chain_steps` so the
        knowledge pack can render the shape. Single-step patterns like
        `summarize_text`, `extract_structured_fields`, `audio_transcription`
        leave it empty; the seed below is the canonical set and any
        addition must be a deliberate one-line diff against both registry
        and this test."""
        multi_step_seed: frozenset[str] = frozenset(
            {
                "multi_step_quality_chain",
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

    def test_positive_patterns_recipe_sections_match_canonical_seed(self) -> None:
        """Exact-seed pin for `Pattern.recipe_sections`. Each positive
        pattern either names the recipe-section keys it should activate
        when it wins a `find_pattern_candidates` scoring pass, or leaves
        the tuple empty to opt out of score-based recipe triggering.

        `multi_step_quality_chain` and `sectioned_form_intake` stay
        empty on purpose — their retrieval hints (`review`, `document`,
        `chain`, `form`, `sections`, `headings`) overlap too heavily
        with generic planner vocabulary, so score-only triggering is
        unreliable; those recipes still reach the planner through the
        phrase-aware signal paths.

        `summarize_text` stays empty because it has no dedicated recipe
        section — the golden example plus base architecture cover it.

        Changing this seed is a deliberate one-line diff against both
        the registry and this test; a drift here almost certainly means
        the recipe selector's intended narrowing got silently widened.
        """
        canonical_seed: dict[str, tuple[str, ...]] = {
            "audio_transcription": ("transcription",),
            "comparison": ("comparison",),
            "document_to_docx_template": ("docx_template",),
            "document_to_pdf_report": ("document_analysis",),
            "document_to_structured_report": ("document_analysis",),
            "extract_structured_fields": ("json_pipeline",),
            "form_field_runtime_inputs": (),
            "multi_step_quality_chain": (),
            "sectioned_form_intake": (),
            "summarize_text": (),
        }

        # Exhaustiveness: every positive pattern in the registry must
        # appear in `canonical_seed`. A future positive pattern added
        # without a seed entry would otherwise silently inherit the
        # dataclass default `()` and bypass this drift check.
        positive_ids = frozenset(
            p.id for p in PATTERN_REGISTRY.values() if p.polarity == "positive"
        )
        assert frozenset(canonical_seed) == positive_ids, (
            f"canonical_seed missing positive patterns: "
            f"{sorted(positive_ids - frozenset(canonical_seed))}; "
            f"or stale entries: "
            f"{sorted(frozenset(canonical_seed) - positive_ids)}"
        )

        # Cross-module contract: every declared recipe-section key must
        # exist in the selector's `RECIPE_SECTIONS` registry. A typo
        # (`"json_pipline"`) on a Pattern would otherwise silently
        # fall through `_filter_recipe_sections` without activating
        # anything.
        from intric.flows.ai_builder.ai_builder_recipe_selector import (
            RECIPE_SECTIONS,
        )

        known_section_keys = frozenset(RECIPE_SECTIONS.keys())

        for pattern_id, expected in canonical_seed.items():
            pattern = PATTERN_REGISTRY[pattern_id]
            assert pattern.recipe_sections == expected, (
                f"{pattern_id}: recipe_sections drift. "
                f"Expected {expected!r}, got {pattern.recipe_sections!r}"
            )
            unknown = frozenset(pattern.recipe_sections) - known_section_keys
            assert not unknown, (
                f"{pattern_id}: recipe_sections references unknown "
                f"selector keys {sorted(unknown)}; must be a subset of "
                f"{sorted(known_section_keys)}"
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

    def test_negative_patterns_declare_no_recipe_sections(
        self, negative_patterns: list[Pattern]
    ) -> None:
        """Negative patterns describe shapes the planner must avoid; they
        must never activate a recipe section. An accidental populated
        `recipe_sections` on a negative would let a score-based trigger
        widen the recipe pack with the anti-pattern's guidance — the
        opposite of what the negative is for."""
        for pattern in negative_patterns:
            assert pattern.recipe_sections == (), (
                f"{pattern.id}: negative pattern must leave recipe_sections "
                f"empty; got {pattern.recipe_sections!r}"
            )


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
    """Public planner-strategy entry points: scoring, slot → qid lookup, and
    the LLM-facing knowledge pack renderer.
    """

    def test_find_pattern_candidates_returns_empty_tuple_for_blank_text(
        self,
    ) -> None:
        """No signal → no candidates. Returning `()` (not a raised
        exception) keeps callers on a single code path when the planner
        state has yet to accumulate any prompt text."""
        assert find_pattern_candidates("") == ()
        assert find_pattern_candidates("   \n   ") == ()

    def test_find_pattern_candidates_matches_on_retrieval_hint_tokens(
        self,
    ) -> None:
        """A prompt containing a literal retrieval-hint token scores
        that pattern above zero. `summarize_text` has the hint token
        `summary`; we assert membership, not position, so the test is
        robust across pattern reorderings."""
        matches = find_pattern_candidates("I want a quick summary of my text")
        matched_ids = {match.pattern.id for match in matches}
        assert "summarize_text" in matched_ids, (
            f"summarize_text should match 'summary of my text'; got {matched_ids}"
        )

    def test_find_pattern_candidates_matches_form_field_runtime_inputs(
        self,
    ) -> None:
        """A prompt that describes runtime form-field variables scores the
        `form_field_runtime_inputs` archetype. Asserts membership only —
        scoring order across patterns is exercised by other tests — so
        this guard survives future pattern reorderings and additional
        overlapping archetypes. Uses `inmatningsfält` and `uses_form_fields`
        to anchor on retrieval-hint tokens unique to this pattern."""
        matches = find_pattern_candidates(
            "Användaren fyller i inmatningsfält som uses_form_fields läser."
        )
        matched_ids = {match.pattern.id for match in matches}
        assert "form_field_runtime_inputs" in matched_ids, (
            f"form_field_runtime_inputs should match runtime-variable prose; "
            f"got {matched_ids}"
        )

    def test_find_pattern_candidates_does_not_match_on_substrings(self) -> None:
        """Word-boundary matching regression guard. A hint token like
        `form` (from `extract_structured_fields`) must not match inside
        `information`; `step` (from `multi_step_quality_chain`) must not
        match inside `stepwise`; `document` (from document-family
        patterns) must not match inside `documentation`. A substring
        match would silently score noise patterns against unrelated
        prompts and poison downstream planner scoring."""
        matches = find_pattern_candidates(
            "I need information about the stepwise documentation"
        )
        matched_ids = {match.pattern.id for match in matches}
        assert "extract_structured_fields" not in matched_ids, (
            f"`form` substring-matched inside `information`: {matched_ids}"
        )
        assert "multi_step_quality_chain" not in matched_ids, (
            f"`step` substring-matched inside `stepwise`: {matched_ids}"
        )
        for doc_pattern_id in (
            "document_to_docx_template",
            "document_to_pdf_report",
            "document_to_structured_report",
        ):
            assert doc_pattern_id not in matched_ids, (
                f"`document` substring-matched inside `documentation`: "
                f"{doc_pattern_id} in {matched_ids}"
            )

    def test_find_pattern_candidates_excludes_zero_score_patterns(self) -> None:
        """Patterns with zero token hits are not emitted. A planner
        consumer iterating the tuple should see only the archetypes that
        actually matched."""
        matches = find_pattern_candidates("summarize my document please")
        for match in matches:
            assert match.score > 0, (
                f"{match.pattern.id}: zero-score pattern should not be in "
                f"candidates; got score={match.score}"
            )

    def test_find_pattern_candidates_never_returns_negative_patterns(
        self,
    ) -> None:
        """Negative archetypes describe shapes to avoid; they must never
        appear in the candidate output. A prompt mentioning 'avoid image
        input' still must not surface `image_input_pipeline`."""
        matches = find_pattern_candidates(
            "template fill with generated pdf avoid image input pipeline"
        )
        for match in matches:
            assert match.pattern.polarity == "positive", (
                f"{match.pattern.id}: negative pattern surfaced in candidates"
            )

    def test_find_pattern_candidates_is_sorted_by_descending_score_then_id(
        self,
    ) -> None:
        """Determinism contract: higher scores come first; ties break on
        ascending pattern id so the planner sees a stable order across
        process restarts."""
        matches = find_pattern_candidates(
            "summarize my document and extract fields into json"
        )
        scores = [match.score for match in matches]
        assert scores == sorted(scores, reverse=True), (
            f"scores not descending: {scores}"
        )
        for idx in range(len(matches) - 1):
            if matches[idx].score == matches[idx + 1].score:
                assert matches[idx].pattern.id < matches[idx + 1].pattern.id, (
                    f"tie not broken on ascending id: "
                    f"{matches[idx].pattern.id} >= {matches[idx + 1].pattern.id}"
                )

    def test_find_pattern_candidates_counts_distinct_hint_tokens_not_repeats(
        self,
    ) -> None:
        """Scoring counts the number of *distinct* hint tokens that appear
        in the input text. A pattern author who repeats the same token
        across multiple hint lines (e.g. `document analysis`,
        `input_type=document ...`, `output_type=document ...`) does not
        earn one point per occurrence — the single input word `document`
        contributes one signal, not three. Otherwise authoring style would
        drive ranking instead of content overlap."""
        # `document_to_structured_report` carries `document` across three
        # hint lines in the live registry; other document patterns carry
        # it across one. If scoring counted repeats, the structured-report
        # pattern would dominate any single-mention-of-document prompt.
        matches = find_pattern_candidates("I need a document that analyzes inputs")
        ids = [m.pattern.id for m in matches]
        assert "document_to_structured_report" in ids, (
            "document_to_structured_report should still score on 'document' "
            "+ 'analyzes' overlap"
        )
        structured = next(
            m for m in matches if m.pattern.id == "document_to_structured_report"
        )
        # The pattern has distinct hint tokens {document, analysis, report,
        # input_type=document, output_type=text, output_type=json,
        # output_mode=pass_through}; the input contributes `document` only
        # on whole-word match (analyzes != analysis, no report).
        assert structured.score == 1, (
            "distinct-token scoring should credit only the unique hit "
            f"('document'), not three times; got score={structured.score}"
        )

    def test_pattern_match_is_frozen_dataclass(self) -> None:
        """Results must not be mutated by consumers. Freezing guards
        against a caller that patches `score` in place between rank and
        render."""
        matches = find_pattern_candidates("summarize")
        assert matches, "summarize should produce at least one match"
        match = matches[0]
        with pytest.raises(FrozenInstanceError):
            match.score = 999  # type: ignore[misc]

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

    def test_render_knowledge_pack_mentions_every_positive_pattern(self) -> None:
        """Silent-drop guard: the knowledge pack must mention every
        positive archetype at least once, so the LLM planner can never
        silently miss a pattern because the renderer's loop was
        short-circuited."""
        rendered = render_knowledge_pack()
        for pattern in PATTERN_REGISTRY.values():
            if pattern.polarity != "positive":
                continue
            assert pattern.id in rendered, (
                f"positive pattern {pattern.id!r} missing from knowledge pack"
            )

    def test_render_knowledge_pack_mentions_every_negative_pattern(self) -> None:
        """Negative archetypes are the 'don't do this' section — omitting
        one would silently drop an anti-pattern warning."""
        rendered = render_knowledge_pack()
        for pattern in PATTERN_REGISTRY.values():
            if pattern.polarity != "negative":
                continue
            assert pattern.id in rendered, (
                f"negative pattern {pattern.id!r} missing from knowledge pack"
            )

    def test_render_knowledge_pack_mentions_every_builder_exposed_capability(
        self,
    ) -> None:
        """Engine-truth capabilities that the builder exposes must all
        land in the pack. `not_exposed` / `engine_only` capabilities are
        filtered out — they are not planner-eligible."""
        rendered = render_knowledge_pack()
        for cap in CAPABILITY_REGISTRY.values():
            if cap.exposure != "builder":
                continue
            assert cap.id in rendered, (
                f"builder-exposed capability {cap.id!r} missing from knowledge pack"
            )

    def test_render_knowledge_pack_is_deterministic(self) -> None:
        """Two invocations must return the exact same bytes. A
        non-deterministic pack would poison LLM prompt caching and
        make planning-state snapshots unreproducible."""
        assert render_knowledge_pack() == render_knowledge_pack()

    def test_render_knowledge_pack_emits_chain_steps_when_present(self) -> None:
        """Patterns with a non-empty `chain_steps` must surface the chain
        tokens in the rendered pack — that is the whole point of the
        field. The existing `multi_step_quality_chain` pattern is the
        canonical carrier; the rendered block must contain an exact
        `chain_steps: a -> b -> c -> d` line (sequence preserved, arrow
        separator pinned) so the LLM reads the sequential shape rather
        than a flat list."""
        rendered = render_knowledge_pack()
        chain_pattern = PATTERN_REGISTRY["multi_step_quality_chain"]
        assert chain_pattern.chain_steps, (
            "multi_step_quality_chain must carry chain_steps for this "
            "test to be meaningful"
        )
        block = _extract_pattern_block(rendered, chain_pattern.id)
        expected_line = "  chain_steps: " + " -> ".join(chain_pattern.chain_steps)
        assert expected_line in block, (
            f"rendered block for {chain_pattern.id} must contain the exact "
            f"chain_steps line {expected_line!r}; block was:\n{block}"
        )

    def test_render_knowledge_pack_omits_chain_steps_when_absent(self) -> None:
        """Single-step patterns with empty `chain_steps` must not emit
        a bare `chain_steps:` header — that would make the pack's
        per-pattern block inconsistent and leak scaffolding prose to
        the planner. `summarize_text` is the canonical single-step
        pattern; its rendered block must not contain the label."""
        rendered = render_knowledge_pack()
        summarize = PATTERN_REGISTRY["summarize_text"]
        assert summarize.chain_steps == (), (
            "summarize_text must carry empty chain_steps for this test to be meaningful"
        )
        summarize_block = _extract_pattern_block(rendered, summarize.id)
        assert "chain_steps:" not in summarize_block, (
            f"single-step pattern {summarize.id} leaked `chain_steps:` "
            f"label; block was:\n{summarize_block}"
        )
