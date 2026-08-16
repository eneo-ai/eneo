"""Which critic invariants are architecture and which are semantic.

The kind is the whole classification a release verdict needs: architecture
invariants are hard-fatal in create and are a different product question, so
they are reported apart from the semantic firing count the gate scores.

This table is a leaf on purpose. `ai_builder_critic_invariants` carries the
evidence callables and drags most of the application in with them, which an
offline statistics tool must not import — the release gate reads the kinds from
here instead. `test_ai_builder_plan_quality_critic.py` pins the two against each
other in both directions, so this is a second FILE, never a second answer.
"""

from __future__ import annotations

from typing import Literal, Mapping

CriticInvariantKind = Literal["architecture", "semantic"]

CRITIC_INVARIANT_KINDS: Mapping[str, CriticInvariantKind] = {
    "action_followup_requires_followup_fields": "semantic",
    "checkpoint_intent_mismatch": "architecture",
    "document_renderer_must_immediately_follow_body_writer": "semantic",
    "docx_terminal_output_alignment": "architecture",
    "explicit_json_contract_request_without_step": "semantic",
    "field_reuse_requires_input_bindings": "semantic",
    "final_text_step_must_reference_relevant_structured_outputs": "semantic",
    "form_fields_declared_must_be_referenced": "semantic",
    "generated_docx_rejects_template_fill": "architecture",
    "mixed_audio_doc_rejects_file_degradation": "architecture",
    "mixed_audio_doc_rejects_pseudo_transcription": "architecture",
    "mixed_audio_doc_requires_real_transcription_step": "architecture",
    "multi_document_compare_requires_all_previous_steps": "architecture",
    "non_terminal_step_document_conversion_forbidden": "architecture",
    "non_terminal_step_template_fill_forbidden": "architecture",
    "pdf_terminal_output_alignment": "architecture",
    "redundant_terminal_json_format_tail_after_final_text_composer": "semantic",
    "rich_workflow_requires_form_fields": "semantic",
    "rich_workflow_requires_json_contract_step": "semantic",
    "rich_workflow_requires_multiple_steps": "semantic",
    "runtime_metadata_requires_form_fields": "semantic",
    "sectioned_form_intake_requires_form_fields": "semantic",
    "simple_text_transform_must_remain_single_step": "semantic",
    "source_reader_required_fields_must_be_captured": "architecture",
    "standalone_audio_requires_transcription_step": "architecture",
    "structured_extraction_requires_json_contract_step": "semantic",
    "template_fill_docx_requires_template_fill_step": "architecture",
    "terminal_renderer_must_not_consume_review_only_step": "semantic",
}
