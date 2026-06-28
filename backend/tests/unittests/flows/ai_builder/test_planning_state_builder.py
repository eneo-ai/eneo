"""Unit tests for `planning_state_builder.carry_forward_persisted_planner_state`.

The helper is the single place the save path merges planner-owned
fields (architecture_commit and monotonic phase) from the previously
persisted state onto a freshly rebuilt one. Integration tests pin the
savepoint wiring; these unit tests pin the merge semantics in isolation
so regressions show up at the merge layer, not two containers deep.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from intric.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
)
from intric.flows.ai_builder.ai_builder_conversation_metadata import (
    metadata_with_slot_classification,
    slot_classification_metadata_from_result,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from intric.flows.ai_builder.ai_builder_slot_classifier import (
    ClassifiedSlot,
    SlotClassificationConfidence,
    SlotClassificationResult,
)
from intric.flows.ai_builder.planning_state import (
    BUILDER_SCHEMA_VERSION,
    FCM_VERSION,
    PLANNER_CONTRACT_VERSION,
    ArchitectureCommit,
    EvidenceRef,
    PlanningState,
    ResolvedSlot,
    SlotConfidence,
    SlotSource,
    StepTriple,
)
from intric.flows.ai_builder.planning_state_builder import (
    _MODEL_VALUE_ACCEPTANCE_POLICIES,
    apply_policy_defaults_from_resolved_slots,
    build_planning_state_from_conversation,
    carry_forward_persisted_planner_state,
    merge_llm_resolved_slots,
)
from intric.flows.ai_builder.question_catalog import legal_slot_values


def _state(
    *,
    phase: str = "discovering",
    architecture_commit: ArchitectureCommit | None = None,
) -> PlanningState:
    return PlanningState(
        fcm_version=FCM_VERSION,
        planner_contract_version=PLANNER_CONTRACT_VERSION,
        builder_schema_version=BUILDER_SCHEMA_VERSION,
        phase=phase,  # type: ignore[arg-type]
        evidence=EvidenceRef(),
        architecture_commit=architecture_commit,
    )


def _commit(hash_char: str = "a") -> ArchitectureCommit:
    return ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="text",
                output_type="text",
                output_mode="pass_through",
            )
        ],
        chosen_patterns=["summarize_text"],
        committed_at=datetime(2026, 4, 23, tzinfo=timezone.utc),
        architecture_hash=hash_char * 64,
    )


def _slot(
    *,
    name: str,
    value: str,
    source: SlotSource,
) -> ResolvedSlot:
    confidence: SlotConfidence = "medium" if source == "policy_default" else "high"
    return ResolvedSlot(
        name=name,
        value=value,
        source=source,
        evidence=[f"{source}:{name}"],
        confidence=confidence,
    )


def _classified(
    slot_name: str,
    value: str,
    confidence: SlotClassificationConfidence,
) -> ClassifiedSlot:
    return ClassifiedSlot(
        slot_name=slot_name,
        value=value,
        confidence=confidence,
        reason=f"{slot_name} classified",
    )


def _slot_classification_metadata(
    *slots: ClassifiedSlot,
    prompt_hash: str = "a" * 64,
) -> dict[str, object]:
    metadata = slot_classification_metadata_from_result(
        SlotClassificationResult(slots=slots),
        prompt_hash=prompt_hash,
    )
    assert metadata is not None
    result = metadata_with_slot_classification(None, metadata)
    assert result is not None
    return result


def test_model_value_acceptance_policies_reference_legal_slot_values() -> None:
    for (slot_name, value), policy in _MODEL_VALUE_ACCEPTANCE_POLICIES.items():
        assert value in legal_slot_values(slot_name)
        for dependent_slot_name, dependent_value in policy.dependent_model_values:
            assert dependent_value in legal_slot_values(dependent_slot_name)


class TestPersistedNone:
    def test_is_noop_when_persisted_is_none(self) -> None:
        rebuilt = _state(phase="awaiting_input")

        carry_forward_persisted_planner_state(rebuilt, None)

        assert rebuilt.architecture_commit is None
        assert rebuilt.phase == "awaiting_input"


class TestArchitectureCommitPreservation:
    def test_carries_forward_when_rebuilt_has_none(self) -> None:
        persisted_commit = _commit()
        rebuilt = _state()
        persisted = _state(architecture_commit=persisted_commit)

        carry_forward_persisted_planner_state(rebuilt, persisted)

        assert rebuilt.architecture_commit is persisted_commit

    def test_does_not_overwrite_explicit_set_on_rebuilt(self) -> None:
        explicit = _commit(hash_char="b")
        persisted_commit = _commit(hash_char="a")
        rebuilt = _state(architecture_commit=explicit)
        persisted = _state(architecture_commit=persisted_commit)

        carry_forward_persisted_planner_state(rebuilt, persisted)

        assert rebuilt.architecture_commit is explicit

    def test_leaves_none_when_neither_side_has_commit(self) -> None:
        rebuilt = _state()
        persisted = _state()

        carry_forward_persisted_planner_state(rebuilt, persisted)

        assert rebuilt.architecture_commit is None


class TestPhaseMonotonicity:
    def test_preserves_advanced_phase_when_rebuild_regressed(self) -> None:
        rebuilt = _state(phase="discovering")
        persisted = _state(phase="plan_proposed")

        carry_forward_persisted_planner_state(rebuilt, persisted)

        assert rebuilt.phase == "plan_proposed"

    def test_keeps_rebuilt_phase_when_already_equal_or_ahead(self) -> None:
        rebuilt = _state(phase="plan_proposed")
        persisted = _state(phase="discovering")

        carry_forward_persisted_planner_state(rebuilt, persisted)

        assert rebuilt.phase == "plan_proposed"

    def test_preserves_ready_to_commit_over_discovering(self) -> None:
        rebuilt = _state(phase="discovering")
        persisted = _state(phase="ready_to_commit")

        carry_forward_persisted_planner_state(rebuilt, persisted)

        assert rebuilt.phase == "ready_to_commit"

    def test_raises_on_unknown_phase(self) -> None:
        # The tuple-based PHASE_ORDER lookup fails loud on unknown
        # phases. If a new PlanningPhase Literal is added without
        # updating the order, .index() raises — preservation never
        # silently degrades.
        rebuilt = _state()
        rebuilt.phase = "discovering"  # valid
        persisted = _state(phase="plan_proposed")
        # Bypass Literal enforcement on persisted to simulate a phase
        # that exists at runtime but was forgotten in _PHASE_ORDER.
        object.__setattr__(persisted, "phase", "brand_new_phase")

        with pytest.raises(ValueError):
            carry_forward_persisted_planner_state(rebuilt, persisted)


class TestReturnValue:
    def test_returns_none_and_mutates_in_place(self) -> None:
        rebuilt = _state()
        persisted = _state(architecture_commit=_commit())

        result = carry_forward_persisted_planner_state(rebuilt, persisted)

        assert result is None
        assert rebuilt.architecture_commit is not None


class TestPolicyDefaults:
    def test_text_runtime_input_is_inferred_from_generic_receive_text_phrase(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Skapa ett enkelt flöde som tar emot en kort text från "
                        "användaren och sammanfattar den i tre tydliga punkter."
                    ),
                )
            ]
        )

        slot = state.resolved_slots["primary_runtime_input"]
        assert slot.value == "text"
        output_slot = state.resolved_slots["terminal_output"]
        assert output_slot.value == "structured_text"

    def test_json_in_json_out_treats_input_as_structured_json_not_text(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Jag vill bygga ett flöde som tar emot JSON och "
                        "returnerar JSON."
                    ),
                )
            ]
        )

        assert state.resolved_slots["primary_runtime_input"].value == "json"
        assert state.resolved_slots["terminal_output"].value == "structured_json"

    def test_json_with_explicit_schema_preserves_input_semantics(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Bygg ett flöde som tar emot en JSON payload och "
                        "returnerar strikt JSON enligt schemat "
                        "{name: string, amount: number, deadline: string}."
                    ),
                )
            ]
        )

        assert state.resolved_slots["primary_runtime_input"].value == "json"
        assert state.resolved_slots["terminal_output"].value == "structured_json"

    def test_document_to_json_extraction_keeps_document_input(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Användaren laddar upp ett PDF-avtal. Flödet ska "
                        "extrahera kundnamn, datum och riskflaggor som "
                        "strukturerad JSON och returnera strukturerad JSON "
                        "som slutresultat."
                    ),
                )
            ]
        )

        assert state.resolved_slots["primary_runtime_input"].value == "documents"
        assert state.resolved_slots["terminal_output"].value == "structured_json"

    def test_document_input_defaults_to_flexible_document_scope(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Build a document analysis flow that accepts uploaded "
                        "documents and produces a written report."
                    ),
                )
            ]
        )

        slot = state.resolved_slots["document_material_scope"]
        assert slot.value == "flexible_document_case"
        assert slot.source == "policy_default"

    def test_multi_source_contradiction_prompt_resolves_compare_slots(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Användaren laddar upp 2-5 underlagsfiler. Flödet ska "
                        "extrahera nyckelfakta som strukturerad JSON från varje fil "
                        "eller från varje dokumentdel, sedan identifiera motsägelser "
                        "mellan källorna i ett separat analyssteg."
                    ),
                )
            ]
        )

        assert state.resolved_slots["document_material_scope"].value == (
            "multiple_documents_case"
        )
        assert state.resolved_slots["comparison_scope"].value == "same_run_compare"

    def test_single_document_compare_prompt_does_not_resolve_same_run_compare(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Bygg ett flöde som jämför ett avtal mot interna riktlinjer "
                        "och skriver en kort rapport."
                    ),
                )
            ]
        )

        assert "comparison_scope" not in state.resolved_slots

    def test_non_comparison_multi_file_prompt_resolves_aggregate_scope_only(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Låt användaren ladda upp flera underlagsfiler och "
                        "sammanfatta dem i en strukturerad rapport."
                    ),
                )
            ]
        )

        assert state.resolved_slots["document_material_scope"].value == (
            "multiple_documents_case"
        )
        assert "comparison_scope" not in state.resolved_slots

    def test_document_input_defaults_to_no_extra_runtime_metadata(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Build a document analysis flow that accepts uploaded "
                        "documents and produces a written report."
                    ),
                )
            ]
        )

        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "no_extra_metadata"
        assert slot.source == "policy_default"

    def test_audio_input_defaults_to_no_extra_runtime_metadata(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Jag vill bygga ett flöde som tar emot en ljudfil, "
                        "transkriberar samtalet och skapar ett Word-dokument."
                    ),
                )
            ]
        )

        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "no_extra_metadata"
        assert slot.source == "policy_default"

    def test_text_input_defaults_to_no_extra_runtime_metadata(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Skapa ett flöde som tar emot text från användaren, "
                        "klassificerar ärendet och skriver ett svar."
                    ),
                )
            ]
        )

        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "no_extra_metadata"
        assert slot.source == "policy_default"

    def test_runtime_input_fields_are_not_overwritten_by_no_metadata_default(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Create a document review flow that accepts PDFs, uses "
                        "input fields for audience and detail level at runtime, "
                        "and produces a DOCX report."
                    ),
                )
            ]
        )

        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "detailed_case_metadata"
        assert slot.source == "heuristic"

    def test_user_supplies_prompt_resolves_detailed_runtime_metadata(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Create a flow where the user supplies customer name, "
                        "analysis request, and optional uploaded files, then "
                        "the flow produces a structured answer."
                    ),
                )
            ]
        )

        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "detailed_case_metadata"
        assert slot.source == "heuristic"

    def test_swedish_audio_prompt_with_terminal_word_file_resolves_core_slots(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Jag vill bygga ett flöde där jag ska skicka in en ljudfil "
                        "som ska transkriberas. Jag vill ha en Word-fil i slutet."
                    ),
                )
            ]
        )

        assert state.resolved_slots["primary_runtime_input"].value == "audio"
        assert state.resolved_slots["terminal_output"].value == "docx_document"
        assert state.resolved_slots["docx_output_mode"].value == "generated_docx"
        assert state.resolved_slots["runtime_metadata_fields"].value == (
            "no_extra_metadata"
        )

    def test_swedish_audio_docx_prompt_with_no_input_fields_keeps_metadata_absent(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Jag vill bygga ett flöde där användaren skickar in "
                        "mötesljud, flödet transkriberar ljudet och skapar en "
                        "Word-rapport med rubriker. Inmatningsfält behövs inte."
                    ),
                )
            ]
        )

        assert state.resolved_slots["primary_runtime_input"].value == "audio"
        assert state.resolved_slots["terminal_output"].value == "docx_document"
        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "no_extra_metadata"
        assert slot.source == "heuristic"

    def test_swedish_audio_recording_prompt_with_terminal_word_file_resolves_core_slots(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Jag vill kunna skicka in en ljudinspelning och få ett "
                        "bra Word-dokument tillbaka."
                    ),
                )
            ]
        )

        assert state.resolved_slots["primary_runtime_input"].value == "audio"
        assert state.resolved_slots["terminal_output"].value == "docx_document"
        assert state.resolved_slots["docx_output_mode"].value == "generated_docx"
        assert state.resolved_slots["runtime_metadata_fields"].value == (
            "no_extra_metadata"
        )

    def test_explicit_audio_meeting_docx_prompt_resolves_audio_with_high_confidence(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Bygg ett flöde där användaren laddar upp en ljudfil vid "
                        "körning. Ljudfilen är en inspelning från ett "
                        "kommunfullmäktigemöte. Flödet ska först transkribera "
                        "ljudfilen till svensk text. Rubrikerna ska inte vara "
                        "inmatningsfält för användaren, utan ska skapas och fyllas "
                        "i utifrån transkriptionen. Slutresultatet ska vara ett "
                        "Word-dokument. Användaren ska bara behöva lämna in "
                        "ljudfilen vid körning."
                    ),
                )
            ]
        )

        slot = state.resolved_slots["primary_runtime_input"]
        assert slot.value == "audio"
        assert slot.source == "heuristic"
        assert slot.confidence == "high"
        assert state.resolved_slots["terminal_output"].value == "docx_document"

    def test_explicitly_uncertain_output_format_keeps_terminal_output_unresolved(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Jag har en svensk ljudinspelning från ett möte och vill "
                        "göra ett flöde av den. Flödet ska ta ljudfilen, förstå "
                        "vad som sades och skapa något användbart som jag kan dela "
                        "vidare efteråt. Jag vet inte exakt vilket format "
                        "slutresultatet ska vara ännu, men det ska kännas "
                        "professionellt och lätt att läsa."
                    ),
                )
            ]
        )

        assert "terminal_output" not in state.resolved_slots

    def test_meeting_followup_goal_resolves_and_derives_structured_analysis(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Jag har en svensk ljudinspelning från ett möte. Flödet "
                        "ska transkribera ljudet och ta fram beslut, nästa steg, "
                        "ansvariga, deadlines och öppna frågor."
                    ),
                )
            ]
        )

        goal = state.resolved_slots["post_processing_goal"]
        assert goal.value == "action_followup"
        assert goal.source == "heuristic"
        assert goal.confidence == "high"
        structured = state.resolved_slots["structured_analysis_need"]
        assert structured.value == "use_structured_analysis"
        assert structured.source == "policy_default"

    def test_transcript_only_goal_does_not_derive_structured_analysis(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Transkribera ljudfilen ordagrant och skapa en PDF med "
                        "bara transkriptionen. Ingen sammanfattning eller analys."
                    ),
                )
            ]
        )

        assert state.resolved_slots["post_processing_goal"].value == (
            "stop_after_primary_operation"
        )
        assert "structured_analysis_need" not in state.resolved_slots

    def test_bare_transcription_goal_stays_unresolved(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content="Jag vill ha ett transkriberingsflöde.",
                )
            ]
        )

        assert state.resolved_slots["primary_runtime_input"].value == "audio"
        assert "post_processing_goal" not in state.resolved_slots
        assert "structured_analysis_need" not in state.resolved_slots

    def test_later_freeform_output_choice_overrides_earlier_uncertainty(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Jag har en svensk ljudinspelning. Jag vet inte exakt "
                        "vilket format slutresultatet ska vara ännu."
                    ),
                ),
                ConversationMessage(
                    role="user",
                    content="Slutresultatet ska vara ett DOCX-dokument.",
                ),
            ]
        )

        assert state.resolved_slots["terminal_output"].value == "docx_document"
        assert state.resolved_slots["docx_output_mode"].value == "generated_docx"


class TestRuntimeMetadataClassificationBoundaries:
    def test_classifier_cannot_override_explicit_negated_runtime_field_request(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Bygg ett transkriptionsflöde där användaren laddar upp "
                        "ljud vid körning. Användaren ska inte fylla i extra "
                        "formulärfält, metadatafält eller inmatningsfält vid "
                        "körning. Rapportfält som datum, språk i ljudet, namn, "
                        "kontaktuppgifter, risker och osäkerheter ska hämtas "
                        "från ljudet och transkriberingen."
                    ),
                )
            ]
        )

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified(
                        "runtime_metadata_fields",
                        "detailed_case_metadata",
                        "high",
                    ),
                )
            ),
            prompt_hash="f" * 64,
            freeform_text="",
        )

        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "no_extra_metadata"
        assert slot.source == "heuristic"
        assert slot.confidence == "high"

    def test_classifier_cannot_override_source_derived_report_fields(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Bygg ett flöde där användaren laddar upp en ljudfil, "
                        "flödet transkriberar ljudet och skapar en DOCX-rapport. "
                        "Alla rapportfält ska hämtas från ljudet/transkriberingen: "
                        "datum, källa, språk i ljudet, ljudkvalitet, namn, "
                        "kontaktuppgifter, risker och osäkerheter. Om något "
                        "saknas ska rapporten skriva Ej nämnt i underlaget."
                    ),
                )
            ]
        )

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified(
                        "runtime_metadata_fields",
                        "detailed_case_metadata",
                        "high",
                    ),
                )
            ),
            prompt_hash="a" * 64,
            freeform_text="",
        )

        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "no_extra_metadata"
        assert slot.source == "heuristic"
        assert slot.confidence == "high"

    def test_classifier_cannot_override_source_derived_document_sections(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Skapa ett flöde som ska få ett worddokument uppladdat "
                        "som input. Varje rubrik och text skall skrivas utifrån "
                        "det ursprungliga dokumentet som helhet varje gång. "
                        "Rubrik: Resursåtgång i form av tidsuppskattning och "
                        "personella resurser. Ange i nedan tabell vilka "
                        "roller/kompetenser som behövs. Rubrik: Ekonomisk "
                        "nytta och kostnader. Ange beräknad totalkostnad för "
                        "genomförandet av lösningsförslaget. När alla steg är "
                        "klara så ska det i slutändan skapas ett "
                        "worddokument som output."
                    ),
                )
            ]
        )

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified(
                        "runtime_metadata_fields",
                        "detailed_case_metadata",
                        "high",
                    ),
                )
            ),
            prompt_hash="b" * 64,
            freeform_text="",
        )

        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "no_extra_metadata"
        assert slot.source == "heuristic"
        assert slot.confidence == "high"
        assert state.resolved_slots["terminal_output"].value == "docx_document"
        assert state.resolved_slots["docx_output_mode"].value == "generated_docx"

    def test_real_runtime_fields_still_resolve_as_metadata_inputs(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Bygg ett ljudflöde där användaren ska fylla i "
                        "ärendenummer och ansvarig enhet vid körning innan "
                        "ljudet transkriberas."
                    ),
                )
            ]
        )

        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "detailed_case_metadata"
        assert slot.source == "heuristic"


class TestSlotClassificationMetadataReplay:
    def test_replays_terminal_output_and_runtime_fields_from_conversation_metadata(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "The user uploads documents and provides customer name, "
                        "case type, and analysis request before receiving a report."
                    ),
                    metadata=_slot_classification_metadata(
                        _classified("primary_runtime_input", "documents", "high"),
                        _classified("terminal_output", "structured_text", "high"),
                        _classified(
                            "runtime_metadata_fields",
                            "detailed_case_metadata",
                            "high",
                        ),
                    ),
                )
            ]
        )

        assert state.resolved_slots["terminal_output"].value == "structured_text"
        assert state.resolved_slots["terminal_output"].source == "model"
        assert state.resolved_slots["runtime_metadata_fields"].value == (
            "detailed_case_metadata"
        )
        commit = derive_architecture_commit_draft(state)
        assert commit is not None
        assert commit.chosen_patterns == [
            "document_to_structured_report",
            "form_field_runtime_inputs",
        ]

    def test_structured_answer_wins_over_classifier_metadata(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content="Make the final answer JSON.",
                    metadata={
                        "question_answer": {
                            "question_id": "final_output_mode",
                            "selected_option_id": "structured_json",
                            "selected_value": "structured_json",
                        },
                        **_slot_classification_metadata(
                            _classified("terminal_output", "structured_text", "high"),
                        ),
                    },
                )
            ]
        )

        slot = state.resolved_slots["terminal_output"]
        assert slot.value == "structured_json"
        assert slot.source == "structured_answer"

    def test_replays_metadata_in_conversation_order_without_replacing_model_slots(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content="Initial preference.",
                    metadata=_slot_classification_metadata(
                        _classified("terminal_output", "structured_text", "high"),
                        prompt_hash="a" * 64,
                    ),
                ),
                ConversationMessage(
                    role="user",
                    content="Later preference.",
                    metadata=_slot_classification_metadata(
                        _classified("terminal_output", "structured_json", "high"),
                        prompt_hash="b" * 64,
                    ),
                ),
            ]
        )

        slot = state.resolved_slots["terminal_output"]
        assert slot.value == "structured_text"
        assert slot.evidence == ["model:terminal_output:" + "a" * 64]

    def test_legacy_metadata_without_slot_classification_replays_without_error(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Skapa ett enkelt flöde som tar emot en kort text från "
                        "användaren och sammanfattar den."
                    ),
                    metadata={"legacy": "kept"},
                )
            ]
        )

        assert state.resolved_slots["primary_runtime_input"].value == "text"


class TestModelSlotMerge:
    def test_model_output_preserves_user_and_flow_sources_but_can_correct_summary(
        self,
    ) -> None:
        state = _state()
        state.resolved_slots = {
            "primary_runtime_input": _slot(
                name="primary_runtime_input",
                value="documents",
                source="structured_answer",
            ),
            "terminal_output": _slot(
                name="terminal_output",
                value="structured_text",
                source="requirements_summary",
            ),
            "runtime_metadata_fields": _slot(
                name="runtime_metadata_fields",
                value="no_extra_metadata",
                source="flow_default",
            ),
        }

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified("primary_runtime_input", "text", "high"),
                    _classified("terminal_output", "pdf_document", "high"),
                    _classified(
                        "runtime_metadata_fields",
                        "detailed_case_metadata",
                        "high",
                    ),
                )
            ),
            prompt_hash="a" * 64,
            freeform_text="",
        )

        assert state.resolved_slots["primary_runtime_input"].value == "documents"
        corrected_output = state.resolved_slots["terminal_output"]
        assert corrected_output.value == "pdf_document"
        assert corrected_output.source == "model"
        assert state.resolved_slots["runtime_metadata_fields"].value == (
            "no_extra_metadata"
        )

    def test_model_raw_post_processing_goal_needs_explicit_text_evidence(
        self,
    ) -> None:
        state = _state()

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified(
                        "post_processing_goal",
                        "stop_after_primary_operation",
                        "high",
                    ),
                    _classified(
                        "structured_analysis_need",
                        "text_only_analysis",
                        "high",
                    ),
                )
            ),
            prompt_hash="a" * 64,
            freeform_text="Jag vill ha ett transkriberingsflöde.",
        )

        assert "post_processing_goal" not in state.resolved_slots
        assert "structured_analysis_need" not in state.resolved_slots

    def test_model_raw_post_processing_goal_commits_when_explicit(
        self,
    ) -> None:
        state = _state()

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified(
                        "post_processing_goal",
                        "stop_after_primary_operation",
                        "high",
                    ),
                )
            ),
            prompt_hash="a" * 64,
            freeform_text="Transkribera ljudet ordagrant utan sammanfattning.",
        )

        slot = state.resolved_slots["post_processing_goal"]
        assert slot.value == "stop_after_primary_operation"
        assert slot.source == "model"

    def test_replayed_model_raw_post_processing_goal_is_rechecked(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content="Jag vill ha ett transkriberingsflöde.",
                    metadata=_slot_classification_metadata(
                        _classified(
                            "post_processing_goal",
                            "stop_after_primary_operation",
                            "high",
                        ),
                        _classified(
                            "structured_analysis_need",
                            "text_only_analysis",
                            "high",
                        ),
                    ),
                )
            ]
        )

        assert "post_processing_goal" not in state.resolved_slots
        assert "structured_analysis_need" not in state.resolved_slots

    def test_replay_drops_newly_blocked_model_value(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Jag vill bygga ett flöde som hjälper mig med dokument "
                        "jag laddar upp. Det ska läsa dokumentet och skapa "
                        "något användbart av det."
                    ),
                    metadata=_slot_classification_metadata(
                        _classified(
                            "post_processing_goal",
                            "structure_key_information",
                            "high",
                        ),
                    ),
                )
            ]
        )

        assert "post_processing_goal" not in state.resolved_slots

    def test_model_raw_post_processing_goal_rejects_empty_evidence_text(
        self,
    ) -> None:
        state = _state()

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified(
                        "post_processing_goal",
                        "stop_after_primary_operation",
                        "high",
                    ),
                )
            ),
            prompt_hash="a" * 64,
            freeform_text="",
        )

        assert "post_processing_goal" not in state.resolved_slots

    def test_medium_model_output_does_not_replace_requirements_summary(self) -> None:
        state = _state()
        state.resolved_slots = {
            "terminal_output": _slot(
                name="terminal_output",
                value="structured_text",
                source="requirements_summary",
            )
        }

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(_classified("terminal_output", "pdf_document", "medium"),)
            ),
            prompt_hash="a" * 64,
            freeform_text="",
        )

        assert state.resolved_slots["terminal_output"].value == "structured_text"

    def test_policy_defaults_generated_docx_after_model_terminal_output(self) -> None:
        state = _state()
        state.resolved_slots = {
            "terminal_output": _slot(
                name="terminal_output",
                value="docx_document",
                source="model",
            )
        }

        apply_policy_defaults_from_resolved_slots(
            state,
            freeform_text=("Slutlig DOCX-rapport skapas efter mänsklig granskning."),
        )

        slot = state.resolved_slots["docx_output_mode"]
        assert slot.value == "generated_docx"
        assert slot.source == "policy_default"

    def test_policy_defaults_do_not_mask_explicit_docx_template_mode(self) -> None:
        state = _state()
        state.resolved_slots = {
            "terminal_output": _slot(
                name="terminal_output",
                value="docx_document",
                source="model",
            )
        }

        apply_policy_defaults_from_resolved_slots(
            state,
            freeform_text="Slutrapporten ska fylla en DOCX-mall.",
        )

        assert "docx_output_mode" not in state.resolved_slots

    def test_high_model_output_replaces_policy_default(self) -> None:
        state = _state()
        state.resolved_slots = {
            "runtime_metadata_fields": _slot(
                name="runtime_metadata_fields",
                value="no_extra_metadata",
                source="policy_default",
            )
        }

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified(
                        "runtime_metadata_fields",
                        "detailed_case_metadata",
                        "high",
                    ),
                )
            ),
            prompt_hash="b" * 64,
            freeform_text="",
        )

        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "detailed_case_metadata"
        assert slot.source == "model"
        assert slot.evidence == [
            "model:runtime_metadata_fields:" + "b" * 64,
        ]

    def test_medium_model_output_does_not_replace_policy_default(self) -> None:
        state = _state()
        state.resolved_slots = {
            "runtime_metadata_fields": _slot(
                name="runtime_metadata_fields",
                value="no_extra_metadata",
                source="policy_default",
            )
        }

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified(
                        "runtime_metadata_fields",
                        "detailed_case_metadata",
                        "medium",
                    ),
                )
            ),
            prompt_hash="c" * 64,
            freeform_text="",
        )

        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "no_extra_metadata"
        assert slot.source == "policy_default"

    def test_medium_model_output_replaces_heuristic_and_fills_missing_slot(
        self,
    ) -> None:
        state = _state(phase="awaiting_input")
        state.resolved_slots = {
            "terminal_output": _slot(
                name="terminal_output",
                value="structured_text",
                source="heuristic",
            )
        }

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified("terminal_output", "pdf_document", "medium"),
                    _classified("primary_runtime_input", "text", "medium"),
                )
            ),
            prompt_hash="d" * 64,
            freeform_text="",
        )

        assert state.resolved_slots["terminal_output"].value == "pdf_document"
        assert state.resolved_slots["primary_runtime_input"].value == "text"
        assert state.phase == "discovering"

    def test_model_output_accepts_json_primary_runtime_input(self) -> None:
        state = _state(phase="awaiting_input")

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified("primary_runtime_input", "json", "high"),
                    _classified("terminal_output", "structured_json", "high"),
                )
            ),
            prompt_hash="d" * 64,
            freeform_text="",
        )

        assert state.resolved_slots["primary_runtime_input"].value == "json"
        assert state.resolved_slots["primary_runtime_input"].source == "model"
        assert state.resolved_slots["terminal_output"].value == "structured_json"

    def test_model_output_persists_secondary_result_obligations(self) -> None:
        state = _state()

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(secondary_obligations=("risks", "actions")),
            prompt_hash="a" * 64,
            freeform_text=(
                "Jämför dokumenten och ta också fram risker och rekommenderade åtgärder."
            ),
        )

        assert [
            signal.value
            for signal in state.signals
            if signal.question_id == "result_obligation"
        ] == ["risks", "actions"]

    def test_model_output_cannot_displace_high_confidence_input_heuristic(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Bygg ett flöde där användaren laddar upp en ljudfil vid "
                        "körning. Slutresultatet ska vara ett Word-dokument. "
                        "Användaren ska bara behöva lämna in ljudfilen vid körning."
                    ),
                )
            ]
        )

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified(
                        "primary_runtime_input",
                        "text_and_documents",
                        "high",
                    ),
                )
            ),
            prompt_hash="d" * 64,
            freeform_text="",
        )

        assert state.resolved_slots["primary_runtime_input"].value == "audio"
        assert state.resolved_slots["primary_runtime_input"].confidence == "high"

    def test_low_model_slot_is_not_persisted(self) -> None:
        state = _state()

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(_classified("terminal_output", "pdf_document", "low"),)
            ),
            prompt_hash="e" * 64,
            freeform_text="",
        )

        assert state.resolved_slots == {}

    def test_unknown_model_slot_is_not_persisted(self) -> None:
        state = _state()

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(_classified("primary_runtime_input", "unknown", "high"),)
            ),
            prompt_hash="f" * 64,
            freeform_text="",
        )

        assert state.resolved_slots == {}

    def test_model_blocked_slot_clears_nonprotected_guess(self) -> None:
        state = _state()
        state.resolved_slots = {
            "terminal_output": _slot(
                name="terminal_output",
                value="structured_text",
                source="heuristic",
            )
        }

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(_classified("terminal_output", "structured_text", "high"),)
            ),
            prompt_hash="f" * 64,
            freeform_text="",
            model_blocked_slots=frozenset({"terminal_output"}),
        )

        assert "terminal_output" not in state.resolved_slots

    def test_model_blocked_slot_preserves_structured_answer(self) -> None:
        state = _state()
        state.resolved_slots = {
            "terminal_output": _slot(
                name="terminal_output",
                value="docx_document",
                source="structured_answer",
            )
        }

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(_classified("terminal_output", "structured_text", "high"),)
            ),
            prompt_hash="f" * 64,
            freeform_text="",
            model_blocked_slots=frozenset({"terminal_output"}),
        )

        assert state.resolved_slots["terminal_output"].value == "docx_document"
        assert state.resolved_slots["terminal_output"].source == "structured_answer"

    def test_non_llm_resolvable_slots_are_not_persisted(self) -> None:
        state = _state()

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified("docx_output_mode", "template_fill_docx", "high"),
                    _classified(
                        "pdf_generation_mode",
                        "pdf_template_requested",
                        "high",
                    ),
                )
            ),
            prompt_hash="g" * 64,
            freeform_text="",
        )

        assert state.resolved_slots == {}

    def test_prompt_hash_is_required(self) -> None:
        state = _state()

        with pytest.raises(ValueError, match="prompt_hash"):
            merge_llm_resolved_slots(
                state,
                SlotClassificationResult(
                    slots=(_classified("primary_runtime_input", "text", "high"),)
                ),
                prompt_hash="",
                freeform_text="",
            )
