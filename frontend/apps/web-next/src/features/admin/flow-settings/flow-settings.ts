import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { EneoApiError, unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

/*
 * The tenant's flow settings as one form: seven admin endpoints under
 * /api/v1/settings, each with its own PATCH. Retention is not here; it is a
 * separate platform concern. Bounds mirror the backend's (settings.py and the
 * flow limit modules); the backend checks every value again.
 */

export type FlowSettings = {
  inputLimits: Schema<"FlowInputLimitsPublic">;
  runtime: Schema<"FlowRuntimePolicyPublic">;
  mapped: Schema<"FlowMappedExecutionPolicyPublic">;
  ragEvidence: Schema<"FlowRagEvidencePolicyPublic">;
  documentRender: Schema<"FlowDocumentRenderLimitsPublic">;
  evidence: Schema<"FlowEvidencePolicyPublic">;
  authoringChat: Schema<"FlowAuthoringChatPolicyPublic">;
};

export type FlowSettingsSection = keyof FlowSettings;

export const FLOW_SETTINGS_KEY = ["admin-flow-settings"] as const;

export function flowSettingsQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: FLOW_SETTINGS_KEY,
    queryFn: async (): Promise<FlowSettings> => {
      const [inputLimits, runtime, mapped, ragEvidence, documentRender, evidence, authoringChat] =
        await Promise.all([
          unwrap(api.GET("/api/v1/settings/flow-input-limits")),
          unwrap(api.GET("/api/v1/settings/flow-runtime-policy")),
          unwrap(api.GET("/api/v1/settings/flow-mapped-execution-policy")),
          unwrap(api.GET("/api/v1/settings/flow-rag-evidence-policy")),
          unwrap(api.GET("/api/v1/settings/flow-document-render-limits")),
          unwrap(api.GET("/api/v1/settings/flow-evidence-policy")),
          unwrap(api.GET("/api/v1/settings/flow-authoring-chat-policy"))
        ]);
      return {
        inputLimits,
        runtime,
        mapped,
        ragEvidence,
        documentRender,
        evidence,
        authoringChat
      };
    }
  });
}

export const INPUT_LIMIT_KEYS = [
  "max_files_per_run",
  "audio_max_files_per_run",
  "audio_max_duration_seconds"
] as const;
export const RUNTIME_KEYS = [
  "max_concurrent_runs",
  "default_step_timeout_seconds",
  "max_step_timeout_seconds"
] as const;
export const MAPPED_KEYS = [
  "max_provider_calls_per_mapped_step",
  "max_estimated_input_tokens_per_mapped_step"
] as const;
export const RAG_EVIDENCE_KEYS = [
  "max_sources_with_recorded_passages",
  "max_recorded_passages_per_source",
  "max_recorded_passage_bytes",
  "max_recorded_passage_bytes_per_step",
  "max_recorded_passage_bytes_per_run_view"
] as const;
export const DOCUMENT_RENDER_KEYS = [
  "max_source_chars",
  "max_blocks",
  "max_text_chars",
  "max_table_rows",
  "max_table_columns",
  "max_table_cells",
  "max_cell_chars",
  "max_list_items",
  "max_structured_nodes",
  "max_structured_depth",
  "max_object_fields"
] as const;
export const EVIDENCE_KEYS = [
  "allow_space_admin_raw_export_class3",
  "allow_run_owner_raw_export_class3",
  "allow_service_key_raw_export_class3"
] as const;

/** The flow chat's default model: a model id, or null for the space's own default. */
export const AUTHORING_CHAT_KEYS = ["completion_model_id"] as const;

export type NumberKey =
  | (typeof INPUT_LIMIT_KEYS)[number]
  | (typeof RUNTIME_KEYS)[number]
  | (typeof MAPPED_KEYS)[number]
  | (typeof RAG_EVIDENCE_KEYS)[number]
  | (typeof DOCUMENT_RENDER_KEYS)[number];
export type FlagKey = (typeof EVIDENCE_KEYS)[number];
export type ModelKey = (typeof AUTHORING_CHAT_KEYS)[number];
export type FieldKey = NumberKey | FlagKey | ModelKey;

/** Every editable value, keyed by its API field (unique across the seven endpoints). */
export type FlowSettingsDraft = { [Key in NumberKey]: number | null } & {
  [Key in FlagKey]: boolean;
} & { [Key in ModelKey]: string | null };

/** The fields each endpoint owns; also the order they are saved in. */
export const SECTION_KEYS = {
  inputLimits: INPUT_LIMIT_KEYS,
  runtime: RUNTIME_KEYS,
  mapped: MAPPED_KEYS,
  ragEvidence: RAG_EVIDENCE_KEYS,
  documentRender: DOCUMENT_RENDER_KEYS,
  evidence: EVIDENCE_KEYS,
  authoringChat: AUTHORING_CHAT_KEYS
} as const satisfies { [Section in FlowSettingsSection]: readonly FieldKey[] };

const SECTIONS = Object.keys(SECTION_KEYS) as FlowSettingsSection[];

/** The fields in the order the page shows them: Save moves focus to the first problem. */
export const FIELD_ORDER: readonly FieldKey[] = SECTIONS.flatMap(
  (section) => SECTION_KEYS[section]
);

const FIELD_KEYS = new Set<string>(FIELD_ORDER);

export function isFieldKey(value: unknown): value is FieldKey {
  return typeof value === "string" && FIELD_KEYS.has(value);
}

export function sectionOf(key: FieldKey): FlowSettingsSection {
  const section = SECTIONS.find((candidate) =>
    (SECTION_KEYS[candidate] as readonly FieldKey[]).includes(key)
  );
  if (!section) throw new Error(`Unknown flow setting ${key}`);
  return section;
}

export function draftFrom(settings: FlowSettings): FlowSettingsDraft {
  const { inputLimits, runtime, mapped, ragEvidence, documentRender, evidence, authoringChat } =
    settings;
  return {
    max_files_per_run: inputLimits.max_files_per_run,
    audio_max_files_per_run: inputLimits.audio_max_files_per_run,
    audio_max_duration_seconds: inputLimits.audio_max_duration_seconds,
    max_concurrent_runs: runtime.max_concurrent_runs,
    default_step_timeout_seconds: runtime.default_step_timeout_seconds,
    max_step_timeout_seconds: runtime.max_step_timeout_seconds,
    max_provider_calls_per_mapped_step: mapped.max_provider_calls_per_mapped_step ?? null,
    max_estimated_input_tokens_per_mapped_step:
      mapped.max_estimated_input_tokens_per_mapped_step ?? null,
    max_sources_with_recorded_passages: ragEvidence.max_sources_with_recorded_passages,
    max_recorded_passages_per_source: ragEvidence.max_recorded_passages_per_source,
    max_recorded_passage_bytes: ragEvidence.max_recorded_passage_bytes,
    max_recorded_passage_bytes_per_step: ragEvidence.max_recorded_passage_bytes_per_step,
    max_recorded_passage_bytes_per_run_view: ragEvidence.max_recorded_passage_bytes_per_run_view,
    max_source_chars: documentRender.max_source_chars,
    max_blocks: documentRender.max_blocks,
    max_text_chars: documentRender.max_text_chars,
    max_table_rows: documentRender.max_table_rows,
    max_table_columns: documentRender.max_table_columns,
    max_table_cells: documentRender.max_table_cells,
    max_cell_chars: documentRender.max_cell_chars,
    max_list_items: documentRender.max_list_items,
    max_structured_nodes: documentRender.max_structured_nodes,
    max_structured_depth: documentRender.max_structured_depth,
    max_object_fields: documentRender.max_object_fields,
    allow_space_admin_raw_export_class3: evidence.allow_space_admin_raw_export_class3 ?? false,
    allow_run_owner_raw_export_class3: evidence.allow_run_owner_raw_export_class3 ?? false,
    allow_service_key_raw_export_class3: evidence.allow_service_key_raw_export_class3 ?? false,
    completion_model_id: authoringChat.completion_model_id ?? null
  };
}

// Backend admission caps: flow_input_limits.py, rag_evidence_policy.py and
// FLOW_DOCUMENT_RENDER_HARD_LIMITS in flow_document_limits.py.
export const MAX_FILES_PER_RUN = 1000;
export const MAX_AUDIO_FILES_PER_RUN = 100;
export const MIN_AUDIO_DURATION_SECONDS = 60;
export const MIN_MAPPED_PROVIDER_CALLS = 2;
export const KILOBYTE = 1024;
const RAG_EVIDENCE_CEILINGS = {
  max_sources_with_recorded_passages: 500,
  max_recorded_passages_per_source: 50,
  max_recorded_passage_bytes: 65_536,
  max_recorded_passage_bytes_per_step: 4_194_304,
  max_recorded_passage_bytes_per_run_view: 16_777_216
} as const;
const DOCUMENT_RENDER_HARD_LIMITS = {
  max_source_chars: 5_000_000,
  max_blocks: 20_000,
  max_text_chars: 5_000_000,
  max_table_rows: 50_000,
  max_table_columns: 100,
  max_table_cells: 500_000,
  max_cell_chars: 100_000,
  max_list_items: 50_000,
  max_structured_nodes: 100_000,
  max_structured_depth: 100,
  max_object_fields: 1_000
} as const;

/**
 * A number field's rules, in API units. `scale` is how many API units one
 * shown unit is (60 for minutes, 1024 for kB). A `clearable` field sends null
 * when emptied, which restores the default. A `required` one needs a value;
 * the mapped call ceiling is neither: its switch sets null (new per-file
 * steps off).
 */
export type NumberBounds = {
  min: number;
  max: number | null;
  scale: number;
  clearable: boolean;
  required: boolean;
};

const plain = (max: number | null, min = 1): NumberBounds => ({
  min,
  max,
  scale: 1,
  clearable: true,
  required: false
});
const kilobytes = (max: number): NumberBounds => ({
  min: KILOBYTE,
  max,
  scale: KILOBYTE,
  clearable: true,
  required: false
});

export function fieldBounds(settings: FlowSettings): { [Key in NumberKey]: NumberBounds } {
  const { inputLimits, runtime } = settings;
  const capacity = runtime.max_concurrent_runs_capacity;
  return {
    max_files_per_run: plain(MAX_FILES_PER_RUN),
    audio_max_files_per_run: plain(MAX_AUDIO_FILES_PER_RUN),
    audio_max_duration_seconds: {
      min: MIN_AUDIO_DURATION_SECONDS,
      max: inputLimits.audio_max_duration_ceiling_seconds,
      scale: 60,
      clearable: true,
      required: false
    },
    // Required: an empty limit is "use the server capacity", its own action.
    max_concurrent_runs: { min: 1, max: capacity, scale: 1, clearable: false, required: true },
    default_step_timeout_seconds: plain(runtime.hard_ceiling_seconds),
    max_step_timeout_seconds: plain(runtime.hard_ceiling_seconds),
    max_provider_calls_per_mapped_step: {
      min: MIN_MAPPED_PROVIDER_CALLS,
      max: null,
      scale: 1,
      clearable: false,
      required: false
    },
    max_estimated_input_tokens_per_mapped_step: plain(null),
    max_sources_with_recorded_passages: plain(
      RAG_EVIDENCE_CEILINGS.max_sources_with_recorded_passages
    ),
    max_recorded_passages_per_source: plain(RAG_EVIDENCE_CEILINGS.max_recorded_passages_per_source),
    max_recorded_passage_bytes: kilobytes(RAG_EVIDENCE_CEILINGS.max_recorded_passage_bytes),
    max_recorded_passage_bytes_per_step: kilobytes(
      RAG_EVIDENCE_CEILINGS.max_recorded_passage_bytes_per_step
    ),
    max_recorded_passage_bytes_per_run_view: kilobytes(
      RAG_EVIDENCE_CEILINGS.max_recorded_passage_bytes_per_run_view
    ),
    max_source_chars: plain(DOCUMENT_RENDER_HARD_LIMITS.max_source_chars),
    max_blocks: plain(DOCUMENT_RENDER_HARD_LIMITS.max_blocks),
    max_text_chars: plain(DOCUMENT_RENDER_HARD_LIMITS.max_text_chars),
    max_table_rows: plain(DOCUMENT_RENDER_HARD_LIMITS.max_table_rows),
    max_table_columns: plain(DOCUMENT_RENDER_HARD_LIMITS.max_table_columns),
    max_table_cells: plain(DOCUMENT_RENDER_HARD_LIMITS.max_table_cells),
    max_cell_chars: plain(DOCUMENT_RENDER_HARD_LIMITS.max_cell_chars),
    max_list_items: plain(DOCUMENT_RENDER_HARD_LIMITS.max_list_items),
    max_structured_nodes: plain(DOCUMENT_RENDER_HARD_LIMITS.max_structured_nodes),
    max_structured_depth: plain(DOCUMENT_RENDER_HARD_LIMITS.max_structured_depth),
    max_object_fields: plain(DOCUMENT_RENDER_HARD_LIMITS.max_object_fields)
  };
}

export function dirtyKeys(draft: FlowSettingsDraft, baseline: FlowSettingsDraft): FieldKey[] {
  return FIELD_ORDER.filter((key) => draft[key] !== baseline[key]);
}

/** Why a field cannot be saved, in API units; the page words it at the field. */
export type FieldProblem =
  | { kind: "required" }
  | { kind: "integer" }
  | { kind: "range"; min: number; max: number }
  | { kind: "min"; min: number }
  | { kind: "no_capacity" }
  | { kind: "timeout_order" };

export type FieldProblems = Partial<Record<FieldKey, FieldProblem>>;

function numberProblem(value: number | null, bounds: NumberBounds): FieldProblem | null {
  if (value === null) return bounds.required ? { kind: "required" } : null;
  if (!Number.isInteger(value)) return { kind: "integer" };
  if (bounds.max !== null && (value < bounds.min || value > bounds.max)) {
    return { kind: "range", min: bounds.min, max: bounds.max };
  }
  return value < bounds.min ? { kind: "min", min: bounds.min } : null;
}

/**
 * The problems Save stops at. Only changed fields are checked: an untouched
 * value is what the server resolved, valid by definition. The normal step
 * timeout may not exceed the longest one (`default_timeout_exceeds_tenant_max`).
 */
export function validateDraft(
  draft: FlowSettingsDraft,
  baseline: FlowSettingsDraft,
  settings: FlowSettings
): FieldProblems {
  const bounds = fieldBounds(settings);
  const problems: FieldProblems = {};
  for (const key of dirtyKeys(draft, baseline)) {
    if (!(key in bounds)) continue;
    const numberKey = key as NumberKey;
    if (numberKey === "max_concurrent_runs" && settings.runtime.max_concurrent_runs_capacity < 1) {
      problems[numberKey] = { kind: "no_capacity" };
      continue;
    }
    const problem = numberProblem(draft[numberKey], bounds[numberKey]);
    if (problem) problems[numberKey] = problem;
  }
  const timeoutsChanged =
    draft.default_step_timeout_seconds !== baseline.default_step_timeout_seconds ||
    draft.max_step_timeout_seconds !== baseline.max_step_timeout_seconds;
  const normal = draft.default_step_timeout_seconds;
  const longest = draft.max_step_timeout_seconds;
  if (
    timeoutsChanged &&
    !problems.default_step_timeout_seconds &&
    !problems.max_step_timeout_seconds &&
    normal !== null &&
    longest !== null &&
    normal > longest
  ) {
    problems.default_step_timeout_seconds = { kind: "timeout_order" };
  }
  return problems;
}

export function firstProblem(problems: FieldProblems): FieldKey | null {
  return FIELD_ORDER.find((key) => problems[key]) ?? null;
}

export type FlowSettingsPatches = {
  inputLimits?: Schema<"FlowInputLimitsUpdate">;
  runtime?: Schema<"FlowRuntimePolicyUpdate">;
  mapped?: Schema<"FlowMappedExecutionPolicyUpdate">;
  ragEvidence?: Schema<"FlowRagEvidencePolicyUpdate">;
  documentRender?: Schema<"FlowDocumentRenderLimitsUpdate">;
  evidence?: Schema<"FlowEvidencePolicyUpdate">;
  authoringChat?: Schema<"FlowAuthoringChatPolicyUpdate">;
};

function changed<Key extends FieldKey>(
  keys: readonly Key[],
  draft: FlowSettingsDraft,
  baseline: FlowSettingsDraft
): Pick<FlowSettingsDraft, Key> | undefined {
  const entries = keys
    .filter((key) => draft[key] !== baseline[key])
    .map((key) => [key, draft[key]]);
  return entries.length > 0
    ? (Object.fromEntries(entries) as Pick<FlowSettingsDraft, Key>)
    : undefined;
}

/**
 * One PATCH body per endpoint with only the changed fields. Null restores
 * the default; for the mapped call ceiling it is the explicit opt-out that
 * blocks new per-file steps, which is what switching it off means.
 */
export function buildPatches(
  draft: FlowSettingsDraft,
  baseline: FlowSettingsDraft
): FlowSettingsPatches {
  const patches: FlowSettingsPatches = {
    inputLimits: changed(INPUT_LIMIT_KEYS, draft, baseline),
    runtime: changed(RUNTIME_KEYS, draft, baseline),
    mapped: changed(MAPPED_KEYS, draft, baseline),
    ragEvidence: changed(RAG_EVIDENCE_KEYS, draft, baseline),
    documentRender: changed(DOCUMENT_RENDER_KEYS, draft, baseline),
    evidence: changed(EVIDENCE_KEYS, draft, baseline),
    authoringChat: changed(AUTHORING_CHAT_KEYS, draft, baseline)
  };
  return Object.fromEntries(
    Object.entries(patches).filter(([, patch]) => patch !== undefined)
  ) as FlowSettingsPatches;
}

export type FlowSettingsWriter = {
  [Section in FlowSettingsSection]: (
    body: NonNullable<FlowSettingsPatches[Section]>
  ) => Promise<FlowSettings[Section]>;
};

export function flowSettingsWriter(api: EneoClient): FlowSettingsWriter {
  return {
    inputLimits: (body) => unwrap(api.PATCH("/api/v1/settings/flow-input-limits", { body })),
    runtime: (body) => unwrap(api.PATCH("/api/v1/settings/flow-runtime-policy", { body })),
    mapped: (body) => unwrap(api.PATCH("/api/v1/settings/flow-mapped-execution-policy", { body })),
    ragEvidence: (body) => unwrap(api.PATCH("/api/v1/settings/flow-rag-evidence-policy", { body })),
    documentRender: (body) =>
      unwrap(api.PATCH("/api/v1/settings/flow-document-render-limits", { body })),
    evidence: (body) => unwrap(api.PATCH("/api/v1/settings/flow-evidence-policy", { body })),
    authoringChat: (body) =>
      unwrap(api.PATCH("/api/v1/settings/flow-authoring-chat-policy", { body }))
  };
}

export type SaveOutcome = {
  /** What each saved endpoint answered: its resolved settings. */
  saved: Partial<FlowSettings>;
  failure: { section: FlowSettingsSection; error: unknown } | null;
};

async function write<Section extends FlowSettingsSection>(
  writer: FlowSettingsWriter,
  section: Section,
  body: NonNullable<FlowSettingsPatches[Section]>
): Promise<FlowSettings[Section]> {
  return writer[section](body);
}

/**
 * Writes one endpoint after the other: every endpoint replaces the tenant's
 * shared flow-settings record, so parallel writes could undo each other. The
 * first refusal stops the rest; what was saved before it stays saved.
 */
export async function saveFlowSettings(
  writer: FlowSettingsWriter,
  patches: FlowSettingsPatches
): Promise<SaveOutcome> {
  const saved: Partial<FlowSettings> = {};
  for (const section of SECTIONS) {
    const body = patches[section];
    if (!body) continue;
    try {
      Object.assign(saved, { [section]: await write(writer, section, body) });
    } catch (error) {
      return { saved, failure: { section, error } };
    }
  }
  return { saved, failure: null };
}

/**
 * The draft after a save: the saved endpoints' fields take the values the
 * server resolved; every other field keeps what the administrator typed.
 */
export function rebaseDraft(
  draft: FlowSettingsDraft,
  settings: FlowSettings,
  sections: readonly FlowSettingsSection[]
): FlowSettingsDraft {
  const resolved = draftFrom(settings);
  const next = { ...draft };
  for (const section of sections) {
    for (const key of SECTION_KEYS[section]) Object.assign(next, { [key]: resolved[key] });
  }
  return next;
}

// Refusals that name the field they are about.
const REFUSAL_FIELDS: Record<string, FieldKey> = {
  max_concurrent_runs_exceeds_server_capacity: "max_concurrent_runs",
  tenant_max_exceeds_env_hard_ceiling: "max_step_timeout_seconds",
  default_timeout_exceeds_tenant_max: "default_step_timeout_seconds",
  flow_authoring_model_without_tools: "completion_model_id",
  flow_authoring_model_unavailable: "completion_model_id"
};

/** The field a refused save is about, when the refusal says: its code, its context or a 422's location. */
export function refusalField(error: unknown): FieldKey | null {
  if (!(error instanceof EneoApiError)) return null;
  const byCode = error.reason ? REFUSAL_FIELDS[error.reason] : undefined;
  if (byCode) return byCode;
  const field = error.context?.field;
  if (isFieldKey(field)) return field;
  if (Array.isArray(error.details)) {
    const location: unknown = (error.details[0] as { loc?: unknown } | undefined)?.loc;
    const name = Array.isArray(location) ? location[location.length - 1] : undefined;
    if (isFieldKey(name)) return name;
  }
  return null;
}
