import { m } from "$lib/paraglide/messages";

import type {
  AIBuilderError,
  AIBuilderErrorCategory,
  AIBuilderErrorDetails,
  AIBuilderErrorDetailValue,
  AIBuilderPublicErrorPayload
} from "./protocol";
import { AIBuilderStreamContractError, parseAIBuilderPublicErrorPayload } from "./protocol";
import type { AIBuilderModelSendBlock } from "./FlowAIBuilderDriver";

const ORIGINAL_DETAILS_PREFIX = "original_details_";

interface ParseAIBuilderErrorInput {
  transport: "apply" | "sse";
  payload: unknown;
  fallbackMessage?: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function stringField(record: Record<string, unknown>, field: string): string | null {
  const value = record[field];
  return typeof value === "string" && value.length > 0 ? value : null;
}

function numberField(record: Record<string, unknown>, field: string): number | undefined {
  const value = record[field];
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function responseBody(error: unknown): Record<string, unknown> | null {
  if (!isRecord(error)) return null;
  if (isRecord(error.response)) return error.response;
  if (isRecord(error.body)) return error.body;
  return null;
}

function errorStatus(error: unknown): number | undefined {
  if (!isRecord(error)) return undefined;
  return numberField(error, "status");
}

function errorStage(error: unknown): string | undefined {
  if (!isRecord(error)) return undefined;
  return stringField(error, "stage") ?? undefined;
}

function errorMessage(
  error: unknown,
  body: Record<string, unknown> | null,
  fallbackMessage: string
): string {
  const bodyMessage = body ? stringField(body, "message") : null;
  if (bodyMessage) return bodyMessage;
  if (isRecord(error)) {
    const recordMessage = stringField(error, "message");
    if (recordMessage) return recordMessage;
  }
  if (error instanceof Error && error.message.length > 0) return error.message;
  return fallbackMessage;
}

function normalizeDetails(value: unknown): AIBuilderErrorDetails {
  if (!isRecord(value)) return {};
  const details: AIBuilderErrorDetails = {};
  for (const [key, detailValue] of Object.entries(value)) {
    if (isDetailValue(detailValue)) {
      details[key] = detailValue;
    }
  }
  return details;
}

function isDetailValue(value: unknown): value is AIBuilderErrorDetailValue {
  return (
    value === null ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  );
}

function publicErrorFromRecord(
  record: Record<string, unknown>,
  fallbackMessage: string
): AIBuilderError | null {
  const publicError = parseAIBuilderPublicErrorPayload(record);
  return publicError ? toAIBuilderError(publicError, fallbackMessage) : null;
}

/** `message` stays the server's prose, for the diagnostic report only; the
 *  reader's words come from `aiBuilderErrorText`. */
export function toAIBuilderError(
  publicError: AIBuilderPublicErrorPayload,
  fallbackMessage?: string
): AIBuilderError {
  return {
    ...publicError,
    schema_version: 2,
    diagnostic_context: publicError.diagnostic_context ?? null,
    details: publicError.details ?? {},
    ...(fallbackMessage !== undefined ? { fallback_message: fallbackMessage } : {})
  };
}

/** Failures this client finds itself, before or instead of a server answer. */
export type AIBuilderClientErrorCode =
  | "unknown"
  | "network"
  | "stream_contract_violation"
  | "flow_unpublished_apply_failed"
  | "model_send_blocked";

export type AIBuilderErrorCode = AIBuilderPublicErrorPayload["code"] | AIBuilderClientErrorCode;

/**
 * A request this client refuses to send, thrown with a code rather than a
 * sentence so the reader is told in their language why nothing happened.
 * The developer message is kept for the diagnostic report.
 */
export class AIBuilderClientRefusal extends Error {
  readonly code: "edit_session_flow_required" | "model_send_blocked";
  readonly details: AIBuilderErrorDetails;

  constructor(
    code: AIBuilderClientRefusal["code"],
    details: AIBuilderErrorDetails = {},
    developerMessage: string = code
  ) {
    super(developerMessage);
    this.name = "AIBuilderClientRefusal";
    this.code = code;
    this.details = details;
  }
}

/** The sentence for a composer whose model cannot start a turn, or null when
 *  it can. One owner for the composer and for a refused request. */
export function modelSendBlockMessage(
  block: AIBuilderModelSendBlock | null,
  { anyModelListed }: { anyModelListed: boolean }
): string | null {
  switch (block) {
    case "models_loading":
      return m.ai_builder_models_loading();
    case "models_failed":
      return m.failed_to_load_models();
    case "model_not_listed":
      return m.ai_builder_model_not_listed();
    case "model_capacity_undeclared":
      return m.ai_builder_model_capacity_undeclared();
    case "model_capacity_too_small":
      return m.ai_builder_model_capacity_too_small();
    case "no_ready_model":
      return anyModelListed ? m.ai_builder_no_ready_model() : m.no_completion_model_description();
    case null:
      return null;
  }
}

const MODEL_SEND_BLOCKS: ReadonlySet<string> = new Set<AIBuilderModelSendBlock>([
  "models_loading",
  "models_failed",
  "model_not_listed",
  "model_capacity_undeclared",
  "model_capacity_too_small",
  "no_ready_model"
]);

function detailNumber(error: AIBuilderError, key: string): string | null {
  const value = error.details[key];
  return typeof value === "number" && Number.isFinite(value) ? String(value) : null;
}

type ErrorCopy = ((error: AIBuilderError) => string | null) | null;

const serverLimitation = () => m.ai_builder_error_server_limitation();
const invalidProposal = () => m.ai_builder_failure_cause_invalid_proposal();
const changedConcurrently = () => m.ai_builder_error_changed_concurrently();
const requestInProgress = () => m.ai_builder_error_request_in_progress();
const planAlreadyHandled = () => m.ai_builder_error_plan_already_handled();

/**
 * The one owner of what an AI Builder error code says to the reader. A null
 * entry (or an entry returning null) has no words of its own: the reader is
 * told which operation failed instead (`fallback_message`). The server's
 * English `message` is never shown; it belongs to the diagnostic report.
 * The record is keyed by the generated code union, so a new server code
 * fails the type check until it is given words or an explicit null.
 */
const ERROR_COPY: Record<AIBuilderErrorCode, ErrorCopy> = {
  architecture_critic_invariant_failed: serverLimitation,
  architecture_materialization_failed: (error) => {
    const disposition = error.details.architecture_repair_disposition;
    if (disposition === "user_action") return m.ai_builder_error_requirements_unbuildable();
    if (disposition === "server_defect") return serverLimitation();
    return null;
  },
  ai_builder_plan_resource_binding_unavailable: () => m.ai_builder_error_resource_unavailable(),
  ai_builder_plan_resource_bindings_missing: () => m.ai_builder_error_resource_bindings_missing(),
  bad_request: (error) => {
    const maxChars = detailNumber(error, "max_chars");
    if (maxChars !== null) return m.ai_builder_error_message_too_long({ max: maxChars });
    const maxAttachments = detailNumber(error, "max_attachments");
    if (maxAttachments !== null) {
      return m.ai_builder_error_too_many_attachments({ max: maxAttachments });
    }
    return null;
  },
  builder_attachment_unavailable: () => m.ai_builder_error_attachment_unavailable(),
  edit_session_flow_required: () => m.ai_builder_error_edit_needs_flow(),
  flow_is_published: () => m.ai_builder_error_flow_is_published(),
  flow_not_published: () => m.ai_builder_error_flow_not_published(),
  flow_owner_required: () => m.flow_error_flow_owner_required(),
  review_stale: () => m.ai_builder_error_review_stale(),
  review_finding_unknown: () => m.ai_builder_error_review_finding_unknown(),
  review_flow_too_large: () => m.ai_builder_error_review_flow_too_large(),
  review_sample_timeout: () => m.ai_builder_review_suggestions_timeout(),
  review_suggestions_invalid_output: () => m.ai_builder_review_suggestions_invalid_output(),
  planner_model_below_evidence_level: () => m.ai_builder_review_suggestions_below_level(),
  flow_space_mismatch: null,
  invalid_ai_builder_settings: () => m.ai_builder_error_invalid_settings(),
  insufficient_scope: () => m.ai_builder_error_insufficient_scope(),
  insufficient_space_permission: () => m.ai_builder_error_insufficient_space_permission(),
  invalid_existing_step_ref: () => m.ai_builder_error_step_changed(),
  // Also raised for a model's malformed step reference, which the reader
  // cannot act on: the failed operation is the honest sentence.
  invalid_plan_step_ref: null,
  invalid_plan_status: planAlreadyHandled,
  invalid_question_payload: (error) =>
    error.details.reason === "client_outdated"
      ? m.ai_builder_error_client_outdated()
      : m.ai_builder_question_delegation_stale(),
  invalid_session_transition: () => m.ai_builder_error_session_state(),
  model_not_available: () => m.ai_builder_model_not_listed(),
  named_result_key_unsupported: () => m.ai_builder_error_named_result_key_unsupported(),
  not_found: () => m.ai_builder_error_not_found(),
  no_planner_model_available: () => m.ai_builder_no_ready_model(),
  pdf_template_unsupported: () => m.ai_builder_error_pdf_template_unsupported(),
  schema_limit_exceeded: () => m.ai_builder_error_schema_limit_exceeded(),
  plan_not_proposed: planAlreadyHandled,
  plan_session_mismatch: () => m.ai_builder_error_plan_replaced(),
  planning_state_payload_too_large: () => m.ai_builder_error_session_too_large(),
  planning_state_version_mismatch: changedConcurrently,
  planner_budget_missing: null,
  planner_model_missing_context_window: () => m.ai_builder_model_capacity_undeclared(),
  planner_model_missing_output_tokens: () => m.ai_builder_model_capacity_undeclared(),
  planner_model_incompatible_token_limits: () => m.ai_builder_model_capacity_too_small(),
  planner_context_limit_exceeded: () => m.ai_builder_failure_cause_request_budget_exhausted(),
  planner_invalid_repair_response: invalidProposal,
  planner_output_too_long: () => m.ai_builder_failure_cause_output_too_long(),
  planner_parse_error: invalidProposal,
  planner_rejected: null,
  planner_stream_failed: null,
  planner_upstream_error: (error) => {
    if (error.details.reason === "reasoning_effort_unsupported") {
      return m.ai_builder_error_reasoning_effort_unsupported();
    }
    if (error.details.provider_exception_class === "rate_limit") {
      return m.ai_builder_error_provider_rate_limited();
    }
    return null;
  },
  proposal_tool_missing: () => m.ai_builder_error_no_proposal(),
  question_recovery_exhausted: null,
  question_recovery_unavailable: null,
  requirements_incomplete: null,
  requirements_not_confirmed: null,
  self_correction_invalid_payload: invalidProposal,
  self_correction_invalid_plan: invalidProposal,
  self_correction_quality_failure: invalidProposal,
  session_creator_required: () => m.ai_builder_error_session_creator_required(),
  session_message_in_progress: requestInProgress,
  session_latest_plan_update_conflict: changedConcurrently,
  session_send_in_progress: requestInProgress,
  session_send_lease_lost: changedConcurrently,
  session_turn_idempotency_conflict: null,
  session_turn_provider_outcome_unknown: () =>
    m.ai_builder_failure_cause_provider_outcome_unknown(),
  stale_plan_revision: () => m.ai_builder_error_plan_changed(),
  stale_revision: () => m.ai_builder_error_flow_changed(),
  template_attachment_selection_invalid: () =>
    m.ai_builder_failure_problem_template_attachment_selection_invalid(),
  template_attachment_unreadable: () =>
    m.ai_builder_failure_problem_template_attachment_unreadable(),
  transcript_checkpoint_requires_audio: () => m.ai_builder_error_transcript_review_needs_audio(),
  transcription_model_required: () => m.ai_builder_missing_transcription_model_description(),
  unsupported_architecture: () => m.ai_builder_error_unsupported_architecture(),
  unsupported_revision_type: null,
  unknown: null,
  network: () => m.ai_builder_error_network(),
  stream_contract_violation: null,
  // Unpublishing succeeded and the apply after it failed: the words are the
  // original failure's.
  flow_unpublished_apply_failed: (error) => {
    const original = error.details.original_code;
    if (typeof original !== "string" || original === "flow_unpublished_apply_failed") return null;
    const details = Object.fromEntries(
      Object.entries(error.details)
        .filter(([key]) => key.startsWith(ORIGINAL_DETAILS_PREFIX))
        .map(([key, value]) => [key.slice(ORIGINAL_DETAILS_PREFIX.length), value])
    );
    return aiBuilderErrorCopy({ ...error, code: original, details });
  },
  model_send_blocked: (error) => {
    const reason = error.details.reason;
    return typeof reason === "string" && MODEL_SEND_BLOCKS.has(reason)
      ? modelSendBlockMessage(reason as AIBuilderModelSendBlock, { anyModelListed: true })
      : null;
  }
};

/** The code's own words for the reader, or null when it has none. */
export function aiBuilderErrorCopy(error: AIBuilderError): string | null {
  const copy = Object.hasOwn(ERROR_COPY, error.code)
    ? ERROR_COPY[error.code as AIBuilderErrorCode]
    : null;
  return copy ? copy(error) : null;
}

/** What the reader is told about an AI Builder error: the code's words, or
 *  else which operation failed. Never the server's English prose. */
export function aiBuilderErrorText(error: AIBuilderError): string {
  return (
    aiBuilderErrorCopy(error) ?? error.fallback_message ?? m.ai_builder_error_fallback_generic()
  );
}

function clientError({
  code,
  category,
  message,
  fallbackMessage,
  details = {}
}: {
  code: AIBuilderErrorCode;
  category: AIBuilderErrorCategory;
  message: string;
  fallbackMessage: string;
  details?: AIBuilderErrorDetails;
}): AIBuilderError {
  return {
    schema_version: 2,
    code,
    category,
    message,
    phase: "client",
    request_id: null,
    eneo_error_code: null,
    diagnostic_context: null,
    details,
    fallback_message: fallbackMessage
  };
}

function parseSsePayload(payload: unknown, fallbackMessage: string): AIBuilderError {
  const record =
    typeof payload === "string" && payload.length > 0
      ? safeJsonRecord(payload)
      : isRecord(payload)
        ? payload
        : null;
  const publicError = record ? publicErrorFromRecord(record, fallbackMessage) : null;
  if (publicError) return publicError;

  return clientError({
    code: "unknown",
    category: "internal",
    message: fallbackMessage,
    fallbackMessage,
    details: record
      ? {
          ...(stringField(record, "code") ? { original_code: stringField(record, "code") } : {})
        }
      : {}
  });
}

function parseApplyPayload(payload: unknown, fallbackMessage: string): AIBuilderError {
  if (payload instanceof AIBuilderStreamContractError) {
    return clientError({
      code: "stream_contract_violation",
      category: "internal",
      message: fallbackMessage,
      fallbackMessage
    });
  }
  if (payload instanceof AIBuilderClientRefusal) {
    return clientError({
      code: payload.code,
      category: "bad_request",
      message: payload.message,
      fallbackMessage,
      details: payload.details
    });
  }
  const body = responseBody(payload);
  const publicError = body ? publicErrorFromRecord(body, fallbackMessage) : null;
  if (publicError) return publicError;

  const status = errorStatus(payload);
  const stage = errorStage(payload);
  const message = errorMessage(payload, body, fallbackMessage);
  const details = normalizeDetails(body?.details);
  const rawCode = body ? stringField(body, "code") : null;

  if (status === 409) {
    return clientError({
      code: "stale_revision",
      category: "conflict",
      message,
      fallbackMessage,
      details
    });
  }

  if (status === 0 || stage === "CONNECTION") {
    return clientError({
      code: "network",
      category: "network",
      message,
      fallbackMessage,
      details: { status: 0, ...(stage ? { stage } : {}) }
    });
  }

  return clientError({
    code: "unknown",
    category: "internal",
    message,
    fallbackMessage,
    details: {
      ...details,
      ...(status !== undefined ? { status } : {}),
      ...(rawCode !== null ? { original_code: rawCode } : {}),
      ...(stage ? { stage } : {})
    }
  });
}

function safeJsonRecord(raw: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(raw);
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function parseAIBuilderError({
  transport,
  payload,
  fallbackMessage = m.ai_builder_error_fallback_generic()
}: ParseAIBuilderErrorInput): AIBuilderError {
  if (transport === "sse") {
    return parseSsePayload(payload, fallbackMessage);
  }
  return parseApplyPayload(payload, fallbackMessage);
}

export function buildUnpublishedApplyFailureError({
  flowId,
  originalError
}: {
  flowId: string;
  originalError: AIBuilderError;
}): AIBuilderError {
  return clientError({
    code: "flow_unpublished_apply_failed",
    category: "conflict",
    message: originalError.message,
    fallbackMessage: originalError.fallback_message ?? m.ai_builder_error_fallback_apply_plan(),
    details: {
      flow_id: flowId,
      original_code: originalError.code,
      ...prefixOriginalDetails(originalError.details)
    }
  });
}

export function isStaleApplyError(error: AIBuilderError | null): boolean {
  return error?.code === "stale_revision";
}

export function isSoftBlockAIBuilderError(error: AIBuilderError): boolean {
  return error.category === "soft_block";
}

function prefixOriginalDetails(details: AIBuilderErrorDetails): AIBuilderErrorDetails {
  return Object.fromEntries(
    Object.entries(details).map(([key, value]) => [`${ORIGINAL_DETAILS_PREFIX}${key}`, value])
  );
}
