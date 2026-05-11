import { IntricError } from "@intric/intric-js";
import { m } from "$lib/paraglide/messages";

export const FLOW_API_ERROR_CODES = [
  "flow_run_required_step_input_missing",
  "flow_run_top_level_file_ids_not_supported",
  "flow_run_idempotency_conflict",
  "typed_io_contract_violation",
  "flow_published_form_schema_invalid",
  "flow_review_stale_revision",
  "flow_review_not_active",
  "flow_review_step_result_not_found",
  "flow_review_checkpoint_not_found",
  "flow_review_reject_reason_required",
  "flow_review_reject_reason_too_long",
  "flow_review_idempotency_key_required",
  "flow_review_not_approved",
  "flow_review_already_resumed",
  "flow_review_rejected",
  "flow_review_cancelled",
  "flow_template_invalid_archive",
  "flow_template_corrupted_archive",
  "flow_template_macro_not_allowed",
  "flow_template_missing_required_parts",
  "flow_template_not_accessible",
  "flow_template_read_only",
  "flow_template_unsupported_extension",
  "flow_template_missing_content",
  "flow_run_rerun_step_inputs_unsupported"
] as const;

export type FlowApiErrorCode = (typeof FLOW_API_ERROR_CODES)[number];
export type FlowApiErrorMessageKey = `flow_error_${FlowApiErrorCode}`;

export type FlowApiErrorContext = {
  step_ids?: string[];
  checkpoint_id?: string;
  step_id?: string;
  step_order?: number;
  payload_field?: string;
};

export type FlowApiErrorDescriptor = {
  code: FlowApiErrorCode;
  messageKey: FlowApiErrorMessageKey;
  context: FlowApiErrorContext;
};

const FLOW_API_ERROR_CODE_SET = new Set<string>(FLOW_API_ERROR_CODES);

const UPLOAD_ERROR_HINTS: Record<string, string> = {
  timeout: " Försök igen med en mindre fil eller kontrollera din internetanslutning.",
  file_too_large: " Välj en mindre fil.",
  network: " Kontrollera din internetanslutning och försök igen."
};

export function classifyUploadError(
  message: string
): "timeout" | "file_too_large" | "network" | "unknown" {
  const lower = message.toLowerCase();
  if (lower.includes("timeout") || lower.includes("timed out")) return "timeout";
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

  return context;
}

function isFlowApiErrorCode(code: string): code is FlowApiErrorCode {
  return FLOW_API_ERROR_CODE_SET.has(code);
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

function descriptorForCode(code: string | null | undefined): FlowApiErrorDescriptor | null {
  if (!code || !isFlowApiErrorCode(code)) return null;
  return {
    code,
    messageKey: messageKeyForCode(code),
    context: {}
  };
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
