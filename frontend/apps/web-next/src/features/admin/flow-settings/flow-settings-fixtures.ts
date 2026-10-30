import type { FlowSettings } from "./flow-settings";

/** Test-only: resolved flow settings as the seven endpoints answer them. */
export function flowSettingsFixture(overrides: Partial<FlowSettings> = {}): FlowSettings {
  return {
    inputLimits: {
      file_max_size_bytes: 52_428_800,
      audio_max_size_bytes: 104_857_600,
      max_files_per_run: null,
      audio_max_files_per_run: 10,
      audio_max_duration_seconds: 7200,
      audio_max_duration_ceiling_seconds: 14_400
    },
    runtime: {
      default_step_timeout_seconds: 300,
      max_step_timeout_seconds: 1200,
      hard_ceiling_seconds: 3540,
      max_concurrent_runs: 8,
      max_concurrent_runs_override: null,
      max_concurrent_runs_capacity: 8
    },
    mapped: {
      version: 1,
      max_provider_calls_per_mapped_step: 100,
      max_estimated_input_tokens_per_mapped_step: null,
      max_provider_calls_source: "deployment_default",
      deployment_default_max_provider_calls: 100
    },
    ragEvidence: {
      version: 1,
      max_sources_with_recorded_passages: 25,
      max_recorded_passages_per_source: 30,
      max_recorded_passage_bytes: 4096,
      max_recorded_passage_bytes_per_step: 131_072,
      max_recorded_passage_bytes_per_run_view: 2_097_152
    },
    documentRender: {
      max_source_chars: 500_000,
      max_blocks: 2000,
      max_text_chars: 500_000,
      max_table_rows: 5000,
      max_table_columns: 50,
      max_table_cells: 50_000,
      max_cell_chars: 20_000,
      max_list_items: 5000,
      max_structured_nodes: 10_000,
      max_structured_depth: 32,
      max_object_fields: 200
    },
    evidence: {
      allow_space_admin_raw_export_class3: false,
      allow_run_owner_raw_export_class3: false,
      allow_service_key_raw_export_class3: false
    },
    authoringChat: { completion_model_id: null },
    ...overrides
  };
}
