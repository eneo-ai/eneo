import {
  FLOW_API_ERROR_CODE,
  FLOW_API_ERROR_CODES,
  IntricError,
  type FlowApiErrorCode
} from "@intric/intric-js";
import type { FlowRunError as FlowRunErrorContract } from "@intric/intric-js";
import { m } from "$lib/paraglide/messages";

export { FLOW_API_ERROR_CODE, FLOW_API_ERROR_CODES };
export type { FlowApiErrorCode };
export type FlowApiErrorMessageKey = `flow_error_${FlowApiErrorCode}`;

export type FlowApiErrorContext = {
  step_ids?: string[];
  checkpoint_id?: string;
  step_id?: string;
  step_order?: number;
  payload_field?: string;
  state?: string;
  expires_at?: string;
  expired_at?: string;
};

export type FlowApiErrorDescriptor = {
  code: FlowApiErrorCode;
  messageKey: FlowApiErrorMessageKey;
  context: FlowApiErrorContext;
};

export type FlowReviewPolicyErrorStep = {
  step_order: number;
  user_description?: string | null;
  review_policy?: unknown | null;
};

export type FlowReviewPolicyAffectedStep = {
  step_order: number;
  user_description: string | null;
};

export type FlowRunError = FlowRunErrorContract;

const FLOW_API_ERROR_CODE_SET = new Set<FlowApiErrorCode>(FLOW_API_ERROR_CODES);

const UPLOAD_ERROR_HINTS: Record<string, string> = {
  timeout: " Försök igen med en mindre fil eller kontrollera din internetanslutning.",
  file_too_large: " Välj en mindre fil.",
  network: " Kontrollera din internetanslutning och försök igen."
};

export function classifyUploadError(
  message: string
): "timeout" | "file_too_large" | "network" | "unknown" {
  const lower = message.toLowerCase();
  if (
    lower.includes("timeout") ||
    lower.includes("timed out") ||
    lower.includes("did not start") ||
    lower.includes("stalled") ||
    lower.includes("server did not respond")
  )
    return "timeout";
  if (lower.includes("too large") || lower.includes("max") || lower.includes("storlek"))
    return "file_too_large";
  if (lower.includes("network") || lower.includes("fetch") || lower.includes("nät"))
    return "network";
  return "unknown";
}

export function getUploadErrorHint(errorKind: ReturnType<typeof classifyUploadError>): string {
  return UPLOAD_ERROR_HINTS[errorKind] ?? "";
}

const MISSING_TEMPLATE_CONTENT_PATTERNS = [
  "selected template file has no binary content",
  "published docx template file has no binary content",
  "file content is missing"
];

function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function readOptionalStringArray(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const strings = value.filter((item): item is string => typeof item === "string");
  return strings.length > 0 ? strings : undefined;
}

function readOptionalString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function readOptionalNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function extractFlowApiErrorContext(value: unknown): FlowApiErrorContext {
  if (!isObject(value)) return {};

  const context: FlowApiErrorContext = {};
  const stepIds = readOptionalStringArray(value.step_ids);
  if (stepIds) context.step_ids = stepIds;

  const checkpointId = readOptionalString(value.checkpoint_id);
  if (checkpointId) context.checkpoint_id = checkpointId;

  const stepId = readOptionalString(value.step_id);
  if (stepId) context.step_id = stepId;

  const stepOrder = readOptionalNumber(value.step_order);
  if (stepOrder !== undefined) context.step_order = stepOrder;

  const payloadField = readOptionalString(value.payload_field);
  if (payloadField) context.payload_field = payloadField;

  const state = readOptionalString(value.state);
  if (state) context.state = state;

  const expiresAt = readOptionalString(value.expires_at);
  if (expiresAt) context.expires_at = expiresAt;

  const expiredAt = readOptionalString(value.expired_at);
  if (expiredAt) context.expired_at = expiredAt;

  return context;
}

function isFlowApiErrorCode(code: string): code is FlowApiErrorCode {
  return FLOW_API_ERROR_CODE_SET.has(code as FlowApiErrorCode);
}

function getResponseCode(error: IntricError): string | null {
  if (isObject(error.response) && typeof error.response.code === "string") {
    return error.response.code;
  }
  return typeof error.code === "string" ? error.code : null;
}

function responseContext(error: IntricError): FlowApiErrorContext {
  if (!isObject(error.response)) return {};
  return extractFlowApiErrorContext(error.response.context);
}

function messageKeyForCode(code: FlowApiErrorCode): FlowApiErrorMessageKey {
  return `flow_error_${code}`;
}

export function isReviewPolicyInvalidRunError(error: FlowRunError | null | undefined): boolean {
  return error?.code === FLOW_API_ERROR_CODE.REVIEW_POLICY_INVALID;
}

export function reviewPolicyRunErrorStepOrder(
  error: FlowRunError | null | undefined
): number | null {
  const stepOrder = error?.step_order;
  return typeof stepOrder === "number" && Number.isFinite(stepOrder) ? stepOrder : null;
}

export function getReviewPolicyAffectedStepsFromRunError(
  error: FlowRunError | null | undefined,
  steps: readonly FlowReviewPolicyErrorStep[]
): FlowReviewPolicyAffectedStep[] {
  if (!isReviewPolicyInvalidRunError(error)) return [];

  const stepOrder = reviewPolicyRunErrorStepOrder(error);
  if (stepOrder !== null) {
    const step = steps.find((candidate) => candidate.step_order === stepOrder);
    return [
      {
        step_order: stepOrder,
        user_description: step?.user_description?.trim() || null
      }
    ];
  }

  return steps
    .filter((step) => step.review_policy != null)
    .map((step) => ({
      step_order: step.step_order,
      user_description: step.user_description?.trim() || null
    }));
}

export function isReviewPolicyRunErrorStepExact(error: FlowRunError | null | undefined): boolean {
  return reviewPolicyRunErrorStepOrder(error) !== null;
}

export function isReviewPolicyRunErrorRelevantForStep(
  error: FlowRunError | null | undefined,
  stepOrder: number,
  reviewPolicy: unknown | null | undefined
): boolean {
  if (!isReviewPolicyInvalidRunError(error)) return true;

  const affectedStepOrder = reviewPolicyRunErrorStepOrder(error);
  if (affectedStepOrder !== null) return affectedStepOrder === stepOrder;

  return reviewPolicy != null;
}

export function getReviewPolicyErrorStepsFromDefinitionSnapshot(
  steps: readonly unknown[]
): FlowReviewPolicyErrorStep[] {
  return steps.flatMap((step): FlowReviewPolicyErrorStep[] => {
    if (!isObject(step)) return [];

    const stepOrder = readOptionalNumber(step.step_order);
    if (stepOrder === undefined) return [];

    return [
      {
        step_order: stepOrder,
        user_description: readOptionalString(step.user_description) ?? null,
        review_policy: step.review_policy ?? null
      }
    ];
  });
}

export function extractFlowApiError(error: unknown): {
  code: FlowApiErrorCode;
  context: FlowApiErrorContext;
} | null {
  if (!(error instanceof IntricError)) return null;

  const code = getResponseCode(error);
  if (!code || !isFlowApiErrorCode(code)) return null;

  return {
    code,
    context: responseContext(error)
  };
}

export function describeFlowApiError(error: unknown): FlowApiErrorDescriptor | null {
  const parsed = extractFlowApiError(error);
  if (!parsed) return null;

  return {
    code: parsed.code,
    messageKey: messageKeyForCode(parsed.code),
    context: parsed.context
  };
}

function descriptorForCode(
  code: string | null | undefined,
  context: FlowApiErrorContext = {}
): FlowApiErrorDescriptor | null {
  if (!code || !isFlowApiErrorCode(code)) return null;
  return {
    code,
    messageKey: messageKeyForCode(code),
    context
  };
}

export function describeFlowRunError(
  error: FlowRunError | null | undefined
): FlowApiErrorDescriptor | null {
  if (!error) return null;

  const context: FlowApiErrorContext = {};
  if (typeof error.step_id === "string") context.step_id = error.step_id;
  if (typeof error.step_order === "number" && Number.isFinite(error.step_order)) {
    context.step_order = error.step_order;
  }

  return descriptorForCode(error.code, context);
}

function resolveFlowApiErrorMessage(descriptor: FlowApiErrorDescriptor): string {
  return m[descriptor.messageKey]();
}

function matchesMissingTemplateContentError(readableMessage: string): boolean {
  const normalized = readableMessage.toLowerCase();
  return MISSING_TEMPLATE_CONTENT_PATTERNS.some((pattern) => normalized.includes(pattern));
}

export function getFlowRuntimeErrorMessage(error: unknown, fallbackMessage: string): string {
  if (!(error instanceof IntricError)) {
    return fallbackMessage;
  }

  const descriptor = describeFlowApiError(error);
  if (descriptor) return resolveFlowApiErrorMessage(descriptor);

  const readable = error.getReadableMessage();
  if (matchesMissingTemplateContentError(readable)) {
    return getFlowRuntimeErrorMessageByCode("flow_template_missing_content") ?? readable;
  }

  return readable;
}

export function getFlowRuntimeErrorMessageByCode(code: string | null | undefined): string | null {
  const descriptor = descriptorForCode(code);
  return descriptor ? resolveFlowApiErrorMessage(descriptor) : null;
}

export function getFlowRunErrorMessage(error: FlowRunError | null | undefined): string | null {
  const descriptor = describeFlowRunError(error);
  return descriptor ? resolveFlowApiErrorMessage(descriptor) : null;
}

const MIME_FRIENDLY_NAMES: Record<string, string> = {
  "application/pdf": "PDF",
  "application/msword": "Word",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word (.docx)",
  "application/vnd.ms-excel": "Excel",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel (.xlsx)",
  "application/vnd.ms-powerpoint": "PowerPoint",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PowerPoint (.pptx)",
  "text/csv": "CSV",
  "application/csv": "CSV",
  "text/plain": "Text",
  "text/html": "HTML",
  "text/markdown": "Markdown",
  "application/json": "JSON",
  "application/xml": "XML",
  "image/png": "PNG",
  "image/jpeg": "JPEG",
  "image/gif": "GIF",
  "image/webp": "WebP",
  "image/svg+xml": "SVG",
  "audio/mpeg": "MP3",
  "audio/wav": "WAV",
  "audio/ogg": "OGG",
  "audio/webm": "WebM (ljud)",
  "audio/mp4": "M4A",
  "video/mp4": "MP4",
  "video/webm": "WebM",
  "audio/*": "Ljudfiler",
  "video/*": "Videofiler",
  "image/*": "Bildfiler"
};

export function friendlyMimeNames(mimetypes: string[]): string[] {
  const names = mimetypes.map((mime) => MIME_FRIENDLY_NAMES[mime] ?? mime);
  return [...new Set(names)];
}
