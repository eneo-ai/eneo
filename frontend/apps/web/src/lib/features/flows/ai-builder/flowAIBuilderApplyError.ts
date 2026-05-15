import type { ApplyError } from "./protocol";

type ApplyApiErrorCode = Exclude<
  ApplyError["code"],
  "flow_unpublished_apply_failed" | "network" | "unknown"
>;

export const APPLY_API_ERROR_CODES = {
  stale_revision: true,
  flow_is_published: true,
  invalid_existing_step_ref: true,
  transcription_model_required: true,
  flow_space_mismatch: true,
  insufficient_scope: true,
  not_found: true
} as const satisfies Record<ApplyApiErrorCode, true>;

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

function errorMessage(error: unknown, body: Record<string, unknown> | null): string {
  const bodyMessage = body ? stringField(body, "message") : null;
  if (bodyMessage) return bodyMessage;
  if (isRecord(error)) {
    const recordMessage = stringField(error, "message");
    if (recordMessage) return recordMessage;
  }
  if (error instanceof Error && error.message.length > 0) return error.message;
  return "Failed to apply plan";
}

function errorContext(body: Record<string, unknown> | null): Record<string, unknown> {
  if (!body || !isRecord(body.context)) return {};
  return body.context;
}

function assertNever(value: never): never {
  throw new Error(`Unhandled AI Builder apply error code: ${value}`);
}

function applyApiError(
  code: ApplyApiErrorCode,
  message: string,
  context: Record<string, unknown>
): ApplyError {
  switch (code) {
    case "stale_revision":
    case "invalid_existing_step_ref":
    case "transcription_model_required":
    case "flow_space_mismatch":
    case "insufficient_scope":
    case "not_found":
      return { code, message, context };
    case "flow_is_published":
      return { code, message, context };
    default:
      return assertNever(code);
  }
}

function isApplyApiErrorCode(code: string): code is ApplyApiErrorCode {
  return code in APPLY_API_ERROR_CODES;
}

export function parseAIBuilderApplyError(error: unknown): ApplyError {
  const body = responseBody(error);
  const status = errorStatus(error);
  const stage = errorStage(error);
  const message = errorMessage(error, body);
  const context = errorContext(body);
  const rawCode = body ? stringField(body, "code") : null;

  if (rawCode !== null && isApplyApiErrorCode(rawCode)) {
    return applyApiError(rawCode, message, context);
  }

  if (status === 409) {
    return {
      code: "stale_revision",
      message,
      context
    };
  }

  if (status === 0 || stage === "CONNECTION") {
    return {
      code: "network",
      message,
      context: { status: 0, ...(stage ? { stage } : {}) }
    };
  }

  return {
    code: "unknown",
    message,
    context: {
      ...context,
      ...(status !== undefined ? { status } : {}),
      ...(rawCode !== null ? { original_code: rawCode } : {}),
      ...(stage ? { stage } : {})
    }
  };
}

export function isStaleApplyError(error: ApplyError | null): boolean {
  return error?.code === "stale_revision";
}
