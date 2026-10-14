import { FLOW_API_ERROR_CODE } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";
import {
  isUnattendedToolRefusal,
  toolRefusalSentence,
  type UnattendedToolRefusal
} from "./flowToolRefusal";

// `subject` is what an issue of the editor's own names, when it names one.
const CODE_TO_MESSAGE: Record<string, (subject?: string) => string> = {
  typed_io_duplicate_step_order: () => m.flow_validation_msg_duplicate_step_order(),
  typed_io_non_contiguous_step_order: () => m.flow_validation_msg_non_contiguous_step_order(),
  typed_io_multiple_flow_input_steps: () => m.flow_validation_msg_multiple_flow_input_steps(),
  typed_io_flow_input_position_invalid: () => m.flow_validation_msg_flow_input_position_invalid(),
  typed_io_invalid_input_source_position: () =>
    m.flow_validation_msg_invalid_input_source_position(),
  typed_io_unsupported_type: () => m.flow_validation_msg_unsupported_type(),
  typed_io_document_source_unsupported: () => m.flow_validation_msg_document_source_unsupported(),
  typed_io_audio_source_unsupported: () => m.flow_validation_msg_audio_source_unsupported(),
  typed_io_file_source_unsupported: () => m.flow_validation_msg_file_source_unsupported(),
  typed_io_invalid_input_source_combination: () =>
    m.flow_validation_msg_invalid_input_source_combination(),
  typed_io_missing_previous_step: () => m.flow_validation_msg_missing_previous_step(),
  typed_io_incompatible_type_chain: () => m.flow_validation_msg_incompatible_type_chain(),
  template_fill_no_template: () => m.flow_validation_msg_template_fill_no_template(),
  template_fill_missing_mappings: () => m.flow_validation_msg_template_fill_missing_mappings(),
  template_fill_orphaned_mappings: () => m.flow_validation_msg_template_fill_orphaned_mappings(),
  template_fill_structured_mapping: () => m.flow_template_fill_json_warning(),
  speaker_mapping_no_participants_field: () =>
    m.flow_validation_msg_speaker_mapping_no_participants_field(),
  output_mode_incompatible: () => m.flow_validation_msg_output_mode_incompatible(),
  "deleted-step-reference": () => m.flow_validation_msg_deleted_step_reference(),
  assistant_save_failed: () => m.flow_validation_msg_assistant_save_failed(),
  http_missing_url: () => m.flow_validation_msg_http_missing_url(),
  tool_missing_tool: () => m.flow_tool_missing_tool(),
  tool_argument_missing: (name = "") => m.flow_tool_argument_missing({ name }),
  // Server-side step-graph issue codes (FlowGraphIssueCode) that authoring
  // can trigger; the raw technical sentence stays available as detail.
  flow_http_post_output_must_be_terminal: () => m.flow_validation_msg_http_post_not_terminal(),
  flow_input_binding_unsupported_key: () => m.flow_validation_msg_input_binding_unsupported_key(),
  flow_input_binding_runtime_input_unused: () =>
    m.flow_validation_msg_input_binding_runtime_input_unused(),
  flow_step_invalid: () => m.flow_validation_msg_flow_step_invalid(),
  flow_input_contract_inapplicable: () => m.flow_validation_msg_input_contract_inapplicable(),
  invalid_input_contract_schema: () => m.flow_validation_msg_invalid_input_contract_schema(),
  invalid_output_contract_schema: () => m.flow_validation_msg_invalid_output_contract_schema(),
  output_contract_type_mismatch: () => m.flow_validation_msg_output_contract_type_mismatch(),
  flow_input_binding_future_step_reference: () => m.flow_validation_msg_input_binding_future_step(),
  flow_input_binding_invalid_step_reference: () =>
    m.flow_validation_msg_input_binding_invalid_step(),
  flow_input_binding_unknown_step_order: () => m.flow_validation_msg_input_binding_unknown_step(),
  flow_input_alias_not_received: () => m.flow_validation_msg_input_alias_not_received(),
  duplicate_step_name: () => m.flow_validation_msg_duplicate_step_name(),
  citation_mode_unsupported: () => m.flow_validation_msg_citation_mode_unsupported(),
  template_fill_requires_docx: () => m.flow_validation_msg_template_fill_requires_docx(),
  output_contract_template_fill_incompatible: () =>
    m.flow_validation_msg_output_contract_template_fill_incompatible(),
  flow_review_policy_invalid: () => m.flow_validation_msg_review_policy_invalid(),
  flow_review_policy_outbound_output_unsupported: () =>
    m.flow_validation_msg_review_policy_outbound_unsupported(),
  transcribe_only_violation: () => m.flow_validation_msg_transcribe_only_violation(),
  flow_audio_transcription_required: () => m.flow_validation_msg_audio_transcription_required(),
  flow_audio_transcription_model_required: () =>
    m.flow_validation_msg_audio_transcription_model_required(),
  flow_speaker_service_not_chosen: () => m.flow_validation_msg_speaker_service_not_chosen(),
  flow_speaker_service_unavailable: () => m.flow_validation_msg_speaker_service_unavailable(),
  flow_step_limit_exceeded: () => m.flow_error_flow_step_limit_exceeded(),
  // The server names three of the editor's own checks differently.
  duplicate_step_order: () => m.flow_validation_msg_duplicate_step_order(),
  step_order_not_contiguous: () => m.flow_validation_msg_non_contiguous_step_order(),
  unsupported_input_type: () => m.flow_validation_msg_unsupported_type(),
  input_contract_type_mismatch: () => m.flow_validation_msg_input_contract_inapplicable(),
  input_contract_source_mismatch: () => m.flow_validation_msg_input_contract_source_mismatch(),
  audio_document_transcript_chain_invalid: () =>
    m.flow_validation_msg_audio_document_chain_invalid(),
  flow_audio_transcription_invalid: () => m.flow_validation_msg_audio_transcription_invalid(),
  flow_has_no_steps: () => m.flow_publish_blocked_no_steps(),
  // The security-classification refusals a save raises. Their facts, when the
  // server sends them, turn this generic sentence into an actionable one
  // (describeClassificationRefusal).
  flow_step_security_classification_mismatch: () =>
    m.flow_error_flow_step_security_classification_mismatch(),
  flow_step_output_classification_write_down: () =>
    m.flow_error_flow_step_output_classification_write_down(),
  flow_step_tool_arguments_classification_write_down: () =>
    m.flow_error_flow_step_tool_arguments_classification_write_down(),
  // The refusals of a step that takes its input from a tool. Their facts, when
  // the server sends them, choose a sentence that says what to change
  // (describeToolStepRefusal).
  typed_io_tool_not_allowed: () => m.flow_error_typed_io_tool_not_allowed(),
  typed_io_tool_invalid_config: () => m.flow_error_typed_io_tool_invalid_config(),
  typed_io_tool_invalid_schema: () => m.flow_error_typed_io_tool_invalid_schema()
};

export function getValidationIssueMessage(code: string, subject?: string): string {
  return CODE_TO_MESSAGE[code]?.(subject) ?? code;
}

export type ParsedValidationError =
  | { kind: "step"; code: string; stepOrder: number; detail?: string; subject?: string }
  | { kind: "assistant"; assistantId: string; message: string }
  | { kind: "flow"; code: string; message: string; detail?: string };

/** What sets the level of a refusal; `external_source` is the server of the step's tool. */
const CLASSIFICATION_CAUSES = ["reads", "external_source", "knowledge", "space"] as const;
type ClassificationCause = (typeof CLASSIFICATION_CAUSES)[number];

function isClassificationCause(value: unknown): value is ClassificationCause {
  return CLASSIFICATION_CAUSES.some((cause) => cause === value);
}

/**
 * The facts of a security-classification refusal: what the step must clear,
 * what it has, and what sets the level. For `tool_arguments_write_down` the
 * levels are those of the data the step sends to its tool and of the tool's
 * server. `qualifyingModelIds` are the space's usable models that would clear
 * it (model refusals only).
 */
export type ClassificationRefusal = {
  kind: "model_below_required" | "output_write_down" | "tool_arguments_write_down";
  requiredLevel: number;
  currentLevel: number | null;
  cause: ClassificationCause;
  sourceStepOrders: number[];
  qualifyingModelIds: string[];
};

const CLASSIFICATION_KIND_BY_CODE: Record<string, ClassificationRefusal["kind"]> = {
  flow_step_security_classification_mismatch: "model_below_required",
  flow_step_output_classification_write_down: "output_write_down",
  flow_step_tool_arguments_classification_write_down: "tool_arguments_write_down"
};

function isLevel(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}

/**
 * The refusal facts of a classification code, or undefined when the payload
 * lacks them: the caller then shows the generic sentence rather than a
 * message built on a guess.
 */
function readClassificationRefusal(
  code: string,
  context: Record<string, unknown>
): ClassificationRefusal | undefined {
  const kind = CLASSIFICATION_KIND_BY_CODE[code];
  if (!kind) return undefined;
  const { required_level: requiredLevel, current_level: current, cause } = context;
  if (!isLevel(requiredLevel)) return undefined;
  if (!isClassificationCause(cause)) return undefined;
  if (current != null && !isLevel(current)) return undefined;
  if (current == null && kind === "output_write_down") return undefined;
  const list = (value: unknown) => (Array.isArray(value) ? value : []);
  const sourceStepOrders = list(context.source_step_orders).filter(isLevel);
  if (cause === "reads" && sourceStepOrders.length === 0) return undefined;
  return {
    kind,
    requiredLevel,
    currentLevel: current ?? null,
    cause,
    sourceStepOrders,
    qualifyingModelIds: list(context.qualifying_model_ids).filter(
      (id): id is string => typeof id === "string"
    )
  };
}

export type ClassificationNames = {
  stepLabel: (stepOrder: number) => string;
  modelName: (modelId: string) => string | undefined;
  /** The organisation's own name for a security level. */
  className: (level: number) => string;
};

/** The actionable sentence for a refusal: what is read, what the model has, what to choose. */
export function describeClassificationRefusal(
  refusal: ClassificationRefusal,
  names: ClassificationNames
): string {
  const name = names.className(refusal.requiredLevel);
  const current = refusal.currentLevel === null ? null : names.className(refusal.currentLevel);
  const why =
    refusal.cause === "reads"
      ? m.flow_validation_classification_reads({
          name,
          sources: refusal.sourceStepOrders.map(names.stepLabel).join(", ")
        })
      : refusal.cause === "external_source"
        ? m.flow_validation_classification_external_source({ name })
        : refusal.cause === "knowledge"
          ? m.flow_validation_classification_knowledge({ name })
          : m.flow_validation_classification_space({ name });
  if (refusal.kind === "tool_arguments_write_down") {
    return `${why} ${m.flow_error_flow_step_tool_arguments_classification_write_down()}`;
  }
  if (refusal.kind === "output_write_down") {
    return `${why} ${m.flow_validation_classification_write_down({
      override: current ?? name,
      name
    })}`;
  }
  const modelState =
    current === null
      ? m.flow_validation_classification_model_none()
      : m.flow_validation_classification_model_level({ name: current });
  const models = refusal.qualifyingModelIds
    .map(names.modelName)
    .filter((name): name is string => Boolean(name));
  const choice =
    models.length > 0
      ? m.flow_validation_classification_choose_model({ models: models.join(", ") })
      : refusal.qualifyingModelIds.length === 0
        ? m.flow_validation_classification_no_model({ name })
        : m.flow_validation_classification_choose_level({ name });
  return `${why} ${modelState} ${choice}`;
}

// Publish raises these outside the step-graph check, so they carry no
// `context.issue_code`; a refused configuration carries the graph check's
// generic one. The typed error code is their identity.
const TOOL_STEP_REFUSAL_CODES: readonly string[] = [
  FLOW_API_ERROR_CODE.TYPED_IO_TOOL_NOT_ALLOWED,
  FLOW_API_ERROR_CODE.TYPED_IO_TOOL_INVALID_CONFIG,
  FLOW_API_ERROR_CODE.TYPED_IO_TOOL_INVALID_SCHEMA
];

const TOOL_ARGUMENT_SENTENCES = {
  composed_text: m.flow_tool_argument_composed_text,
  nested_reference: m.flow_tool_argument_nested_reference,
  step_not_earlier: m.flow_tool_argument_step_not_earlier,
  unknown_reference: m.flow_tool_argument_unknown_reference,
  missing_required: m.flow_tool_argument_missing_required,
  outside_schema: m.flow_tool_argument_outside_schema
};
type ToolArgumentProblem = keyof typeof TOOL_ARGUMENT_SENTENCES;

function isToolArgumentProblem(value: unknown): value is ToolArgumentProblem {
  return typeof value === "string" && Object.hasOwn(TOOL_ARGUMENT_SENTENCES, value);
}

const TOOL_CONFIG_FIELD = "input_config.tool";
const TOOL_CONFIG_SENTENCES = {
  input_type: m.flow_tool_config_input_type,
  output_mode: m.flow_tool_config_output_mode,
  "input_config.runtime_input": m.flow_tool_config_uploads,
  [TOOL_CONFIG_FIELD]: m.flow_tool_config_unreadable
};
type ToolConfigField = keyof typeof TOOL_CONFIG_SENTENCES;

function isToolConfigField(value: string): value is ToolConfigField {
  return Object.hasOwn(TOOL_CONFIG_SENTENCES, value);
}

/** What the server's facts say a tool step is refused for. */
type ToolStepRefusal =
  | { kind: "not_allowed"; refusal: UnattendedToolRefusal }
  | { kind: "config"; field: ToolConfigField }
  | { kind: "argument"; argument: string; problem: ToolArgumentProblem };

/**
 * The facts of a tool step's refusal, or undefined when the payload lacks
 * them or holds a value this client does not know: the caller then shows the
 * code's generic sentence.
 */
function readToolStepRefusal(
  code: string,
  context: Record<string, unknown>
): ToolStepRefusal | undefined {
  if (code === FLOW_API_ERROR_CODE.TYPED_IO_TOOL_NOT_ALLOWED) {
    return isUnattendedToolRefusal(context.refusal)
      ? { kind: "not_allowed", refusal: context.refusal }
      : undefined;
  }
  if (code !== FLOW_API_ERROR_CODE.TYPED_IO_TOOL_INVALID_CONFIG) return undefined;
  const { field, argument, problem } = context;
  if (argument !== undefined) {
    return typeof argument === "string" && argument && isToolArgumentProblem(problem)
      ? { kind: "argument", argument, problem }
      : undefined;
  }
  if (typeof field !== "string") return undefined;
  if (isToolConfigField(field)) return { kind: "config", field };
  // A value inside the tool configuration that cannot be read is named by its path.
  return field.startsWith(`${TOOL_CONFIG_FIELD}.`)
    ? { kind: "config", field: TOOL_CONFIG_FIELD }
    : undefined;
}

/** The sentence for a tool step's refusal: what is wrong and what to change. */
export function describeToolStepRefusal(refusal: ToolStepRefusal): string {
  switch (refusal.kind) {
    case "not_allowed":
      return toolRefusalSentence(refusal.refusal);
    case "config":
      return TOOL_CONFIG_SENTENCES[refusal.field]();
    case "argument":
      return TOOL_ARGUMENT_SENTENCES[refusal.problem]({ argument: refusal.argument });
  }
}

/**
 * Structured identity of a server-side validation failure, read from the
 * error payload the backend emits: context.issue_code + step_order, or one of
 * the tool step refusal codes.
 */
export function parseServerValidationIdentity(error: { response?: unknown }): {
  code: string;
  stepOrder: number | null;
  field: string | null;
  reference: string | null;
  classification?: ClassificationRefusal;
  toolRefusal?: ToolStepRefusal;
} | null {
  // The backend's GeneralError body arrives as EneoError.response. Apart from
  // the tool step refusal codes, context.issue_code is the one validation
  // discriminator: any other symbolic top-level code alone is NOT treated as
  // validation, so unrelated domain errors are never misrouted into the banner.
  const response =
    typeof error.response === "object" && error.response !== null
      ? (error.response as Record<string, unknown>)
      : null;
  if (!response) return null;
  const context =
    typeof response.context === "object" && response.context !== null
      ? (response.context as Record<string, unknown>)
      : null;
  if (!context) return null;
  const toolCode =
    typeof response.code === "string" && TOOL_STEP_REFUSAL_CODES.includes(response.code)
      ? response.code
      : null;
  const code =
    toolCode ??
    (typeof context.issue_code === "string" && context.issue_code ? context.issue_code : null);
  if (!code) return null;
  const stepOrder = typeof context.step_order === "number" ? context.step_order : null;
  const field = typeof context.field === "string" && context.field ? context.field : null;
  const reference =
    typeof context.reference === "string" && context.reference ? context.reference : null;
  const classification = readClassificationRefusal(code, context);
  const toolRefusal = readToolStepRefusal(code, context);
  return {
    code,
    stepOrder,
    field,
    reference,
    ...(classification ? { classification } : {}),
    ...(toolRefusal ? { toolRefusal } : {})
  };
}

/**
 * Prefixes that encode `{code}:{stepOrder}` after the prefix.
 * Both typed-io and step-config errors are step-scoped.
 */
const STEP_SCOPED_PREFIXES = ["flow:typed-io:", "flow:step-config:", "flow:server:"] as const;
const ASSISTANT_PREFIX = "assistant:";
const FLOW_PREFIX = "flow:";

/**
 * Parse a validation error map entry into a structured object.
 *
 * Key formats:
 *   - `flow:typed-io:{code}:{stepOrder}`
 *   - `flow:step-config:{code}:{stepOrder}`
 *   - `assistant:{assistantId}`
 *   - `flow:{code}`
 */
export function parseValidationError(key: string, values: string[]): ParsedValidationError | null {
  for (const prefix of STEP_SCOPED_PREFIXES) {
    if (key.startsWith(prefix)) {
      const rest = key.slice(prefix.length);
      const lastColon = rest.lastIndexOf(":");
      const stepOrder = lastColon === -1 ? NaN : parseInt(rest.slice(lastColon + 1), 10);
      if (isNaN(stepOrder)) {
        // A flow-scoped server rejection has no step suffix; it still
        // belongs to the banner with the translated (or raw) message.
        if (prefix === "flow:server:") {
          return { kind: "flow", code: rest, message: values[0] ?? rest, detail: values[0] };
        }
        return null;
      }
      return {
        kind: "step",
        code: rest.slice(0, lastColon),
        stepOrder,
        detail: values[0],
        subject: values[1]
      };
    }
  }

  if (key.startsWith(ASSISTANT_PREFIX)) {
    const assistantId = key.slice(ASSISTANT_PREFIX.length);
    return { kind: "assistant", assistantId, message: values[0] ?? key };
  }

  if (key.startsWith(FLOW_PREFIX)) {
    const code = key.slice(FLOW_PREFIX.length);
    return { kind: "flow", code, message: values[0] ?? key, detail: values[0] };
  }

  return null;
}
