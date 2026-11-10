import { EneoApiError, getErrorMessage } from "@/lib/api/errors";
import { FlowEditorError } from "./editor-api";
import { HTTP_CONFIG_KEYS } from "./step-configs";
import { EDITABLE_STEP_FIELDS, isJsonObject, type StepConfig } from "./step-types";

/**
 * Where the editor shows a problem: the field it is about, or the form. The
 * core's refusals carry a `code` and a `context` that often names the step
 * (`step_order`, `step_id`) and the field (`field`, a dotted path such as
 * `input_config.auth.token`); a request validation error names the place in
 * the request body instead. Both land on the field the editor shows for
 * that place.
 */

export const FIELD_ANCHORS = [
  "user_description",
  "prompt",
  "completion_model",
  "completion_model_kwargs",
  "knowledge",
  "attachments",
  "input_source",
  "input_type",
  "input_config.runtime_input",
  "input_config.text_processing",
  "input_config.long_material",
  "input_config.http",
  "input_config.http.auth",
  "input_config.http.more",
  "input_config.tool",
  "input_bindings",
  "output_mode",
  "output_type",
  "output_config.http",
  "output_config.http.auth",
  "output_config.http.body",
  "output_config.http.more",
  "output_config.template",
  // The first of the template's fields that needs a value.
  "output_config.template.fields",
  "output_config.speaker_mapping",
  "output_config.citation_mode",
  "output_config.retrieval_policy",
  "review_policy",
  "output_classification_override",
  "timeout_seconds",
  "input_contract",
  "output_contract"
] as const;

export type FieldAnchor = (typeof FIELD_ANCHORS)[number];

export type FieldProblems = Partial<Record<FieldAnchor, string>>;

/** A part of the HTTP fields with an anchor of its own; the rest is shown at the address. */
type HttpPart = "auth" | "body" | "more";

/** The HTTP part a config key names (`custom_headers[0]` is a header, in the "more" fold). */
function httpPart(key: string): HttpPart | null {
  if (key === "auth" || key === "body") return key;
  if (key === "timeout_seconds" || key.startsWith("custom_headers")) return "more";
  return null;
}

/** The HTTP part a defect the core names (`context.http_error`) is about, when it is not the address. */
const HTTP_ERROR_PARTS: Record<string, HttpPart> = {
  HTTP_MISSING_AUTH: "auth",
  HTTP_INVALID_BODY_JSON: "body",
  HTTP_BODY_NOT_ALLOWED_FOR_GET: "body",
  HTTP_TIMEOUT_OUT_OF_RANGE: "more",
  HTTP_INVALID_HEADER_NAME: "more"
};

/** The anchor of a part of the HTTP fields, or of the address for a part without one. */
export function httpAnchor(
  base: "input_config.http" | "output_config.http",
  part: HttpPart | null | undefined
): FieldAnchor {
  const anchor = part ? `${base}.${part}` : base;
  return (FIELD_ANCHORS as readonly string[]).includes(anchor) ? (anchor as FieldAnchor) : base;
}

/** The editor's field for a dotted path of the step's configuration. */
export function anchorForPath(
  path: string,
  step: Pick<StepConfig, "input_source" | "output_mode">
): FieldAnchor | null {
  const [head = "", second = ""] = path.split(".");
  if (head === "input_config") {
    if (second === "tool") return "input_config.tool";
    if (second === "runtime_input") return "input_config.runtime_input";
    if (second === "text_processing") return "input_config.text_processing";
    if (second === "long_material") return "input_config.long_material";
    if (step.input_source === "http_get") return httpAnchor("input_config.http", httpPart(second));
    if (step.input_source === "tool") return "input_config.tool";
    return null;
  }
  if (head === "output_config") {
    if (second === "speaker_mapping") return "output_config.speaker_mapping";
    if (second === "citation_mode") return "output_config.citation_mode";
    if (second === "retrieval_policy") return "output_config.retrieval_policy";
    if (step.output_mode === "template_fill") return "output_config.template";
    if (
      step.output_mode === "http_post" &&
      (second === "" ||
        (HTTP_CONFIG_KEYS as readonly string[]).includes(second) ||
        httpPart(second) !== null)
    ) {
      return httpAnchor("output_config.http", httpPart(second));
    }
    return null;
  }
  if (head === "input_bindings") return "input_bindings";
  if (head === "prompt") return "prompt";
  if (head === "completion_model") return "completion_model";
  if (head === "completion_model_kwargs") return "completion_model_kwargs";
  if (head === "groups" || head === "websites" || head === "integration_knowledge_list") {
    return "knowledge";
  }
  if (head === "attachments") return "attachments";
  return (FIELD_ANCHORS as readonly string[]).includes(head) ? (head as FieldAnchor) : null;
}

/** The field a refusal code is about when its context names none. */
const CODE_ANCHORS: Record<string, FieldAnchor> = {
  typed_io_invalid_input_source_position: "input_source",
  typed_io_flow_input_position_invalid: "input_source",
  typed_io_multiple_flow_input_steps: "input_source",
  typed_io_missing_previous_step: "input_source",
  typed_io_document_source_unsupported: "input_type",
  typed_io_audio_source_unsupported: "input_type",
  typed_io_file_source_unsupported: "input_type",
  typed_io_incompatible_type_chain: "input_type",
  typed_io_unsupported_type: "input_type",
  unsupported_input_type: "input_type",
  typed_io_invalid_input_source_combination: "input_type",
  flow_audio_transcription_required: "input_type",
  flow_audio_transcription_model_required: "input_type",
  typed_io_invalid_output_mode_combination: "output_mode",
  transcribe_only_violation: "output_mode",
  template_fill_requires_docx: "output_mode",
  flow_http_post_output_must_be_terminal: "output_mode",
  typed_io_tool_invalid_config: "input_config.tool",
  typed_io_tool_invalid_schema: "input_config.tool",
  typed_io_tool_not_allowed: "input_config.tool",
  typed_io_tool_invalid_arguments: "input_config.tool",
  flow_step_tool_arguments_classification_write_down: "input_config.tool",
  flow_step_security_classification_mismatch: "completion_model",
  flow_assistant_model_provider_required: "completion_model",
  flow_step_output_classification_write_down: "output_classification_override",
  flow_review_policy_invalid: "review_policy",
  flow_review_policy_outbound_output_unsupported: "review_policy",
  flow_step_name_reserved_variable: "user_description",
  flow_step_name_step_alias: "user_description",
  duplicate_step_name: "user_description",
  flow_input_binding_unsupported_key: "input_bindings",
  flow_input_binding_runtime_input_unused: "input_bindings",
  flow_input_binding_future_step_reference: "input_bindings",
  flow_input_binding_invalid_step_reference: "input_bindings",
  flow_input_binding_unknown_step_order: "input_bindings",
  flow_input_alias_not_received: "input_bindings",
  flow_step_read_lost_producer: "input_bindings",
  flow_input_contract_inapplicable: "input_contract",
  invalid_input_contract_schema: "input_contract",
  input_contract_type_mismatch: "input_contract",
  input_contract_source_mismatch: "input_contract",
  invalid_output_contract_schema: "output_contract",
  output_contract_type_mismatch: "output_contract",
  output_contract_template_fill_incompatible: "output_contract",
  citation_mode_unsupported: "output_config.citation_mode"
};

/**
 * Message keys for the core's step-graph issue codes (`context.issue_code`)
 * that have no `flow_error_*` text of their own, as the reference editor
 * names them (`flowStepValidationMessages.ts`).
 */
const ISSUE_MESSAGE_KEYS: Record<string, string> = {
  typed_io_multiple_flow_input_steps: "flow_validation_msg_multiple_flow_input_steps",
  typed_io_flow_input_position_invalid: "flow_validation_msg_flow_input_position_invalid",
  typed_io_invalid_input_source_position: "flow_validation_msg_invalid_input_source_position",
  typed_io_unsupported_type: "flow_validation_msg_unsupported_type",
  typed_io_document_source_unsupported: "flow_validation_msg_document_source_unsupported",
  typed_io_audio_source_unsupported: "flow_validation_msg_audio_source_unsupported",
  typed_io_file_source_unsupported: "flow_validation_msg_file_source_unsupported",
  typed_io_invalid_input_source_combination: "flow_validation_msg_invalid_input_source_combination",
  typed_io_missing_previous_step: "flow_validation_msg_missing_previous_step",
  typed_io_incompatible_type_chain: "flow_validation_msg_incompatible_type_chain",
  flow_http_post_output_must_be_terminal: "flow_validation_msg_http_post_not_terminal",
  flow_input_binding_unsupported_key: "flow_validation_msg_input_binding_unsupported_key",
  flow_input_binding_runtime_input_unused: "flow_validation_msg_input_binding_runtime_input_unused",
  flow_step_invalid: "flow_validation_msg_flow_step_invalid",
  flow_input_contract_inapplicable: "flow_validation_msg_input_contract_inapplicable",
  invalid_input_contract_schema: "flow_validation_msg_invalid_input_contract_schema",
  invalid_output_contract_schema: "flow_validation_msg_invalid_output_contract_schema",
  output_contract_type_mismatch: "flow_validation_msg_output_contract_type_mismatch",
  flow_input_binding_future_step_reference: "flow_validation_msg_input_binding_future_step",
  flow_input_binding_invalid_step_reference: "flow_validation_msg_input_binding_invalid_step",
  flow_input_binding_unknown_step_order: "flow_validation_msg_input_binding_unknown_step",
  flow_input_alias_not_received: "flow_validation_msg_input_alias_not_received",
  duplicate_step_name: "flow_validation_msg_duplicate_step_name",
  citation_mode_unsupported: "flow_validation_msg_citation_mode_unsupported",
  template_fill_requires_docx: "flow_validation_msg_template_fill_requires_docx",
  template_binding_not_scalar: "flow_validation_msg_template_binding_not_scalar",
  output_contract_template_fill_incompatible:
    "flow_validation_msg_output_contract_template_fill_incompatible",
  flow_review_policy_invalid: "flow_validation_msg_review_policy_invalid",
  flow_review_policy_outbound_output_unsupported:
    "flow_validation_msg_review_policy_outbound_unsupported",
  transcribe_only_violation: "flow_validation_msg_transcribe_only_violation",
  flow_audio_transcription_required: "flow_validation_msg_audio_transcription_required",
  flow_audio_transcription_model_required: "flow_validation_msg_audio_transcription_model_required",
  flow_live_transcription_model_unavailable:
    "flow_validation_msg_live_transcription_model_unavailable",
  input_contract_source_mismatch: "flow_validation_msg_input_contract_source_mismatch",
  unsupported_input_type: "flow_validation_msg_unsupported_type"
};

/**
 * The editor's sentence for each HTTP defect the core names: a save refusal's
 * `context.http_error` and a connection test's `error_code` use the same codes.
 * `HTTP_STATUS_ERROR` is absent: its sentence needs the test's status code.
 */
export const HTTP_ERROR_KEYS: Record<string, string> = {
  HTTP_MISSING_URL: "flow_step_editor_http_url_missing",
  HTTP_INVALID_URL: "flow_step_editor_http_url_invalid",
  HTTP_VARIABLE_RESOLUTION_FAILED: "http_test_variable_resolution_failed",
  HTTP_UNRESOLVED_STORED_SECRET: "http_test_saved_secret_unavailable",
  HTTP_MISSING_AUTH: "http_test_auth_missing",
  HTTP_INVALID_BODY_JSON: "http_test_body_invalid",
  HTTP_BODY_NOT_ALLOWED_FOR_GET: "http_test_body_not_allowed",
  HTTP_TIMEOUT_OUT_OF_RANGE: "http_test_timeout_invalid",
  HTTP_TIMEOUT: "http_test_timeout",
  HTTP_CONNECTION_REFUSED: "http_test_unreachable",
  HTTP_BLOCKED_URL: "http_test_blocked",
  HTTP_RESPONSE_TOO_LARGE: "http_test_response_too_large",
  HTTP_CREDENTIALS_REQUIRE_HTTPS: "flow_step_editor_http_credentials_need_https",
  HTTP_INVALID_HEADER_NAME: "flow_step_editor_http_header_name_invalid"
};

export type Translator = ((key: string, values?: Record<string, string | number>) => string) & {
  has: (key: string) => boolean;
};

/**
 * The reader's sentence for a flow refusal code, or null when the catalog has
 * none. `values` fill what the sentence names (a refusal's `reference`).
 */
export function refusalMessage(
  code: string | null | undefined,
  t: Translator,
  values?: Record<string, string>
): string | null {
  if (!code) return null;
  const issueKey = ISSUE_MESSAGE_KEYS[code];
  if (issueKey && t.has(issueKey)) return t(issueKey, values);
  const errorKey = `flow_error_${code}`;
  return t.has(errorKey) ? t(errorKey, values) : null;
}

export type EditorProblem = {
  /** The field the problem is shown at; null shows it with the form. */
  anchor: FieldAnchor | null;
  message: string;
  /** Another step's problem (a save checks the whole flow), by its order. */
  otherStepOrder: number | null;
  code: string | null;
};

function contextString(context: Record<string, unknown>, key: string): string | null {
  const value = context[key];
  return typeof value === "string" && value ? value : null;
}

function contextNumber(context: Record<string, unknown>, key: string): number | null {
  const value = context[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** The step fields a request validation error names (`body.step_edits.0.changes.timeout_seconds`). */
function validationPaths(error: EneoApiError): string[] {
  const details = error.details;
  const errors = isJsonObject(details) && Array.isArray(details.errors) ? details.errors : [];
  return errors.flatMap((entry) => {
    if (!isJsonObject(entry)) return [];
    const location = entry.location ?? entry.loc;
    const parts = Array.isArray(location)
      ? location.map(String)
      : typeof location === "string"
        ? location.split(".")
        : [];
    const changes = parts.lastIndexOf("changes");
    const rest = changes >= 0 ? parts.slice(changes + 1) : parts;
    const start = rest.findIndex((part) =>
      [...EDITABLE_STEP_FIELDS, "prompt", "completion_model", "completion_model_kwargs"].includes(
        part as never
      )
    );
    return start >= 0 ? [rest.slice(start).join(".")] : [];
  });
}

/** Where and how the editor shows a failed save of this step. */
export function describeSaveError(
  error: unknown,
  step: {
    stepId: string;
    stepOrder: number;
    config: Pick<StepConfig, "input_source" | "output_mode">;
  },
  t: Translator
): EditorProblem {
  if (!(error instanceof EneoApiError)) {
    return {
      anchor: null,
      message: t("flow_step_editor_save_failed"),
      otherStepOrder: null,
      code: null
    };
  }
  const context = error instanceof FlowEditorError ? error.context : {};
  const code = error.reason ?? null;
  const issueCode = contextString(context, "issue_code");
  const httpErrorKey = HTTP_ERROR_KEYS[contextString(context, "http_error") ?? ""];
  const message =
    (httpErrorKey ? t(httpErrorKey) : null) ??
    refusalMessage(issueCode, t) ??
    refusalMessage(code, t) ??
    (error.status === 422 ? t("flow_step_editor_value_invalid") : getErrorMessage(error, t));

  const stepOrder = contextNumber(context, "step_order");
  const stepId = contextString(context, "step_id");
  const otherStep =
    (stepId !== null && stepId !== step.stepId) ||
    (stepId === null && stepOrder !== null && stepOrder !== step.stepOrder);
  if (otherStep) {
    return { anchor: null, message, otherStepOrder: stepOrder, code };
  }

  const field = contextString(context, "field") ?? validationPaths(error)[0] ?? null;
  return {
    anchor: refusalAnchor(context, code, step.config, field),
    message,
    otherStepOrder: null,
    code
  };
}

/**
 * The field of `step` a refusal is about: the one its `field` path names (the
 * part of the HTTP config its defect names), else the one its codes are about;
 * null for none.
 */
export function refusalAnchor(
  context: Record<string, unknown>,
  code: string | null | undefined,
  step: Pick<StepConfig, "input_source" | "output_mode">,
  field: string | null = contextString(context, "field")
): FieldAnchor | null {
  const fieldAnchor = field ? anchorForPath(field, step) : null;
  const issueCode = contextString(context, "issue_code");
  // A refusal of the whole HTTP config names its defect: show it at that part.
  const httpErrorPart = HTTP_ERROR_PARTS[contextString(context, "http_error") ?? ""];
  return (
    (fieldAnchor === "input_config.http" || fieldAnchor === "output_config.http"
      ? httpAnchor(fieldAnchor, httpErrorPart)
      : fieldAnchor) ??
    (issueCode ? CODE_ANCHORS[issueCode] : undefined) ??
    (code ? CODE_ANCHORS[code] : undefined) ??
    null
  );
}

export function isStaleRevision(error: unknown): boolean {
  return error instanceof EneoApiError && error.reason === "stale_revision";
}
