import type {
  AIBuilderError,
  AIBuilderErrorCategory,
  AIBuilderErrorContext,
  AIBuilderErrorContextValue,
  AIBuilderErrorPhase
} from "./protocol";

interface ParseAIBuilderErrorInput {
  transport: "apply" | "sse";
  payload: unknown;
  fallbackMessage?: string;
}

const VALID_CATEGORIES = new Set<AIBuilderErrorCategory>([
  "bad_request",
  "conflict",
  "internal",
  "network",
  "not_found",
  "soft_block",
  "unauthorized",
  "upstream"
]);

const VALID_PHASES = new Set<AIBuilderErrorPhase>([
  "client",
  "planner",
  "proposal",
  "question",
  "question_recovery",
  "requirements",
  "router",
  "self_correction"
]);

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

function normalizeContext(value: unknown): AIBuilderErrorContext {
  if (!isRecord(value)) return {};
  const context: AIBuilderErrorContext = {};
  for (const [key, contextValue] of Object.entries(value)) {
    if (isContextValue(contextValue)) {
      context[key] = contextValue;
    }
  }
  return context;
}

function isContextValue(value: unknown): value is AIBuilderErrorContextValue {
  return (
    value === null ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  );
}

function publicErrorFromRecord(record: Record<string, unknown>): AIBuilderError | null {
  if (record.schema_version !== 1) return null;
  const code = stringField(record, "code");
  const category = stringField(record, "category");
  const message = stringField(record, "message");
  const phase = stringField(record, "phase");
  if (
    code === null ||
    category === null ||
    message === null ||
    phase === null ||
    !VALID_CATEGORIES.has(category as AIBuilderErrorCategory) ||
    !VALID_PHASES.has(phase as AIBuilderErrorPhase)
  ) {
    return null;
  }

  return {
    schema_version: 1,
    code,
    category: category as AIBuilderErrorCategory,
    message,
    phase: phase as AIBuilderErrorPhase,
    request_id: stringField(record, "request_id"),
    intric_error_code: numberField(record, "intric_error_code") ?? null,
    context: normalizeContext(record.context)
  };
}

function clientError({
  code,
  category,
  message,
  context = {}
}: {
  code: string;
  category: AIBuilderErrorCategory;
  message: string;
  context?: AIBuilderErrorContext;
}): AIBuilderError {
  return {
    schema_version: 1,
    code,
    category,
    message,
    phase: "client",
    request_id: null,
    intric_error_code: null,
    context
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
    context: record
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
  const context = normalizeContext(body?.context);
  const rawCode = body ? stringField(body, "code") : null;

  if (status === 409) {
    return clientError({
      code: "stale_revision",
      category: "conflict",
      message,
      context
    });
  }

  if (status === 0 || stage === "CONNECTION") {
    return clientError({
      code: "network",
      category: "network",
      message,
      context: { status: 0, ...(stage ? { stage } : {}) }
    });
  }

  return clientError({
    code: "unknown",
    category: "internal",
    message,
    context: {
      ...context,
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
    context?: AIBuilderErrorContext;
  } = {}
): AIBuilderError {
  const { code = "unknown", category = "internal", context = {} } = options;
  return clientError({ code, category, message, context });
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
    context: {
      flow_id: flowId,
      original_code: originalError.code,
      ...prefixOriginalContext(originalError.context)
    }
  });
}

export function isStaleApplyError(error: AIBuilderError | null): boolean {
  return error?.code === "stale_revision";
}

export function isSoftBlockAIBuilderError(error: AIBuilderError): boolean {
  return error.category === "soft_block";
}

function prefixOriginalContext(context: AIBuilderErrorContext): AIBuilderErrorContext {
  return Object.fromEntries(
    Object.entries(context).map(([key, value]) => [`original_context_${key}`, value])
  );
}
