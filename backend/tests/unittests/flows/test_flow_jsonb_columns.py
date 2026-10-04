"""A new JSONB column in a Flow table must trigger a review.

This compares the discovered columns with a reviewed list. It does not check how
a column is parsed, versioned or handled when corrupt; that is decided and
tested where the column is read and written.
"""

from __future__ import annotations

from sqlalchemy import JSON

from eneo.database.tables import flow_tables
from eneo.database.tables.tenant_table import Tenants

_REVIEWED_JSONB_COLUMNS = frozenset(
    """
    builder_plans.proposal_json
    builder_sessions.conversation
    builder_sessions.latest_turn_error_jsonb
    builder_sessions.latest_turn_request_jsonb
    builder_sessions.planning_state_jsonb
    flow_live_transcripts.segments
    flow_package_imports.failure_json
    flow_package_imports.import_plan_json
    flow_package_imports.selected_mappings_json
    flow_provider_calls.summarization_input
    flow_retention_holds.created_by_actor
    flow_retention_holds.released_by_actor
    flow_run_audit_outbox.actor_snapshot
    flow_run_review_checkpoint_edits.payload_json
    flow_run_review_checkpoints.current_payload_json
    flow_run_review_checkpoints.next_step_ids_json
    flow_run_review_checkpoints.original_payload_json
    flow_run_review_checkpoints.output_contract_json
    flow_runs.dispatch_last_error
    flow_runs.error_json
    flow_runs.input_payload_json
    flow_runs.output_payload_json
    flow_step_attempt_resolved_inputs.resolved_input_edges_jsonb
    flow_step_attempts.input_payload_json
    flow_step_attempts.output_payload_json
    flow_step_attempts.provenance_json
    flow_step_results.input_payload_json
    flow_step_results.model_parameters_json
    flow_step_results.output_payload_json
    flow_step_transcript_sources.detail_json
    flow_step_transcript_sources.segments_json
    flow_step_transcript_words.words_json
    flow_steps.input_bindings
    flow_steps.input_config
    flow_steps.input_contract
    flow_steps.output_config
    flow_steps.output_contract
    flow_steps.review_policy
    flow_template_assets.placeholders
    flow_transcript_correction_revisions.occurrences_json
    flow_transcript_correction_revisions.speaker_edits_json
    flow_transcript_corrections.occurrences_json
    flow_transcript_corrections.speaker_edits_json
    flow_versions.definition_json
    flows.metadata_json
    tenants.flow_settings
    """.split()
)


def _discovered_jsonb_columns() -> set[str]:
    columns = {
        f"{model.__table__.name}.{column.name}"
        for model in vars(flow_tables).values()
        if getattr(model, "__module__", None) == flow_tables.__name__
        and hasattr(model, "__table__")
        for column in model.__table__.columns
        if isinstance(column.type, JSON)
    }
    flow_settings = Tenants.flow_settings.property.columns[0]
    columns.add(f"{Tenants.__table__.name}.{flow_settings.name}")
    return columns


def test_flow_jsonb_columns_match_the_reviewed_list() -> None:
    discovered = _discovered_jsonb_columns()

    assert discovered == _REVIEWED_JSONB_COLUMNS, (
        "The JSONB columns of the Flow and Builder tables (plus "
        "tenants.flow_settings) no longer match the reviewed list. Add or remove "
        "a column here only together with behavior tests for how it is parsed; "
        "its schema version and corrupt-value behavior are decided at the "
        "parsing site, not here. "
        f"Unreviewed: {sorted(discovered - _REVIEWED_JSONB_COLUMNS)}. "
        f"Missing: {sorted(_REVIEWED_JSONB_COLUMNS - discovered)}."
    )
