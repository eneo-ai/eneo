import type {
  AIBuilderError,
  AIBuilderErrorCategory,
  AIBuilderErrorDetails,
  AIBuilderErrorDetailValue,
  AIBuilderPublicErrorPayload
} from "./protocol";
import { parseAIBuilderPublicErrorPayload } from "./protocol";

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

function publicErrorFromRecord(record: Record<string, unknown>): AIBuilderError | null {
  const publicError = parseAIBuilderPublicErrorPayload(record);
  return publicError ? toAIBuilderError(publicError) : null;
}

export function toAIBuilderError(publicError: AIBuilderPublicErrorPayload): AIBuilderError {
  return {
    ...publicError,
    schema_version: 2,
    diagnostic_context: publicError.diagnostic_context ?? null,
    details: publicError.details ?? {}
  };
}

function clientError({
  code,
  category,
  message,
  details = {}
}: {
  code: string;
  category: AIBuilderErrorCategory;
  message: string;
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
    details
  };
}

function parseSsePayload(payload: unknown, fallbackMessage: string): AIBuilderError {
  const record =
    typeof payload === "string" && payload.length > 0
      ? safeJsonRecord(payload)
      : isRecord(payload)
        ? payload
        : null;
  const publicError = record ? publicErrorFromRecord(record) : null;
  if (publicError) return publicError;

  return clientError({
    code: "unknown",
    category: "internal",
    message: fallbackMessage,
    details: record
      ? {
          ...(stringField(record, "code") ? { original_code: stringField(record, "code") } : {})
        }
      : {}
  });
}

function parseApplyPayload(payload: unknown, fallbackMessage: string): AIBuilderError {
  const body = responseBody(payload);
  const publicError = body ? publicErrorFromRecord(body) : null;
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
      details
    });
  }

  if (status === 0 || stage === "CONNECTION") {
    return clientError({
      code: "network",
      category: "network",
      message,
      details: { status: 0, ...(stage ? { stage } : {}) }
    });
  }

  return clientError({
    code: "unknown",
    category: "internal",
    message,
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
  fallbackMessage = "AI Builder failed. Please try again."
}: ParseAIBuilderErrorInput): AIBuilderError {
  if (transport === "sse") {
    return parseSsePayload(payload, fallbackMessage);
  }
  return parseApplyPayload(payload, fallbackMessage);
}

export function buildClientAIBuilderError(
  message: string,
  options: {
    code?: string;
    category?: AIBuilderErrorCategory;
    details?: AIBuilderErrorDetails;
  } = {}
): AIBuilderError {
  const { code = "unknown", category = "internal", details = {} } = options;
  return clientError({ code, category, message, details });
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
    Object.entries(details).map(([key, value]) => [`original_details_${key}`, value])
  );
}
