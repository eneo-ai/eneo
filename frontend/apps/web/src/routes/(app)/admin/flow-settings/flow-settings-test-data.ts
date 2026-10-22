// Page data for the Flow settings DOM tests: an admin with both retention permissions.

export function pageData(mappedOverrides: Record<string, unknown> = {}) {
  return {
    access: { admin: true, retentionManage: true, retentionHolds: true },
    flowRetentionPolicy: {
      run_debug_evidence_days: null,
      flow_runtime_upload_abandonment_days: null,
      flow_retention_hold_max_review_days: 365
    },
    flowRunRetentionPolicy: {
      scope: "organization",
      scope_id: "tenant-1",
      local_policy: null,
      inherited_policy: null,
      effective: {
        state: "off",
        mode: null,
        effective_days: null,
        source: "none",
        contributors: { organization: null, space: null, flow: null }
      }
    },
    flowRunRetentionReviewQueue: {
      items: [],
      count: 0,
      has_more: false,
      next_cursor: null
    },
    spaceTargets: {
      items: [
        { id: "space-1", name: "Inköp" },
        { id: "space-2", name: "Juridik" }
      ],
      count: 2,
      has_more: false
    },
    flowRetentionHolds: { items: [], has_more: false, review_limit_days: 365 },
    holdReviewLimit: { days: 365, is_default: true },
    flowInputLimits: {
      file_max_size_bytes: 10 * 1024 * 1024,
      audio_max_size_bytes: 200 * 1024 * 1024,
      max_files_per_run: null,
      audio_max_files_per_run: 10,
      audio_max_duration_seconds: 5 * 60 * 60,
      audio_max_duration_ceiling_seconds: 8 * 60 * 60
    },
    flowRuntimePolicy: {
      default_step_timeout_seconds: 600,
      max_step_timeout_seconds: 3540,
      hard_ceiling_seconds: 3540,
      max_concurrent_runs: 4,
      max_concurrent_runs_capacity: 8
    },
    mappedExecutionPolicy: {
      version: 1,
      max_provider_calls_per_mapped_step: 40,
      max_estimated_input_tokens_per_mapped_step: null,
      max_provider_calls_source: "organization",
      deployment_default_max_provider_calls: 100,
      ...mappedOverrides
    },
    ragEvidencePolicy: {
      max_sources_with_recorded_passages: 25,
      max_recorded_passages_per_source: 5,
      max_recorded_passage_bytes: 4096,
      max_recorded_passage_bytes_per_step: 131_072
    }
  };
}
