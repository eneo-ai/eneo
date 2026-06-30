/**
 * Normalized error handling for backend API calls. Every failed request — on
 * the server (eneoApi) or in the browser (browserApi) — is surfaced as an
 * EneoApiError carrying the HTTP status, the backend error code, a readable
 * message and the trace id of the failing request.
 */

/** A FastAPI validation error entry (422 responses). */
interface ValidationDetail {
  loc?: (string | number)[];
  msg?: string;
  type?: string;
}

export class EneoApiError extends Error {
  /** HTTP status of the failing response. */
  readonly status: number;
  /** Backend error code (`eneo_error_code`, see backend ErrorCodes enum). */
  readonly code?: number;
  /** Trace id of the failing request, for correlation with backend logs. */
  readonly traceId?: string;
  /** Structured error payload (`details` on GeneralError), when present. */
  readonly details?: unknown;

  constructor(
    message: string,
    options: { status: number; code?: number; traceId?: string; details?: unknown }
  ) {
    super(message);
    this.name = "EneoApiError";
    this.status = options.status;
    this.code = options.code;
    this.traceId = options.traceId;
    this.details = options.details;
  }
}

export function extractTraceId(headers: Headers): string | undefined {
  return headers.get("x-trace-id") ?? headers.get("x-correlation-id") ?? undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Extracts a message and error code from the three error body shapes the
 * backend produces:
 *  1. GeneralError: `{ message, eneo_error_code, details?, ... }`
 *  2. HTTPException: `{ detail: string }` or `{ detail: { message?, code? } }`
 *  3. FastAPI validation (422): `{ detail: [{ loc, msg, type }, ...] }`
 */
function parseErrorBody(body: unknown): { message?: string; code?: number; details?: unknown } {
  if (!isRecord(body)) return {};

  if (typeof body.message === "string") {
    return {
      message: body.message,
      code: typeof body.eneo_error_code === "number" ? body.eneo_error_code : undefined,
      details: body.details ?? undefined
    };
  }

  const detail = body.detail;
  if (typeof detail === "string") return { message: detail };
  if (Array.isArray(detail)) {
    const messages = (detail as ValidationDetail[])
      .map((entry) => entry.msg)
      .filter((msg): msg is string => typeof msg === "string");
    return { message: messages.join("; ") || "Validation error", details: detail };
  }
  if (isRecord(detail)) {
    return {
      message: typeof detail.message === "string" ? detail.message : undefined,
      code: typeof detail.code === "number" ? detail.code : undefined
    };
  }

  return {};
}

export function apiErrorFromResponse(response: Response, body: unknown): EneoApiError {
  const { message, code, details } = parseErrorBody(body);
  return new EneoApiError(message ?? `Request failed with status ${response.status}`, {
    status: response.status,
    code,
    traceId: extractTraceId(response.headers),
    details
  });
}

/**
 * Unwraps an openapi-fetch result, throwing an EneoApiError on failure. Use as
 * the body of every queryFn/mutationFn:
 *
 *   queryFn: () => unwrap(api.GET("/api/v1/dashboard/"))
 */
export async function unwrap<T>(
  result: Promise<{ data?: T; error?: unknown; response: Response }>
): Promise<T> {
  const { data, error, response } = await result;
  if (error !== undefined || !response.ok) throw apiErrorFromResponse(response, error);
  return data as T;
}

/**
 * Backend error code → i18n message key. Mirrors the SvelteKit app's
 * getErrorMessage mapping; codes without an entry fall back to the backend's
 * English message. When the backend adds a code, add the `eneo_error_{code}`
 * key to src/lib/i18n/extra/{en,sv}.json (or the Svelte catalogs) and the
 * entry below.
 */
const ERROR_MESSAGE_KEYS: Record<number, string> = {
  // Authorization & authentication
  9001: "eneo_error_9001", // UNAUTHORIZED
  9005: "eneo_error_9005", // AUTHENTICATION_ERROR
  9019: "eneo_error_9019", // USER_INACTIVE
  9025: "eneo_error_9025", // TENANT_SUSPENDED
  // Model & provider issues
  9002: "eneo_error_9002", // UNSUPPORTED_MODEL
  9020: "eneo_error_9020", // NO_MODEL_SELECTED
  9026: "eneo_error_9026", // API_KEY_NOT_CONFIGURED
  9031: "eneo_error_9031", // PROVIDER_INACTIVE
  9033: "eneo_error_9033", // MODEL_NOT_AVAILABLE
  9034: "eneo_error_9034", // KNOWLEDGE_MODEL_UNAVAILABLE
  9035: "eneo_error_9035", // SECURITY_CLASSIFICATION_MISMATCH
  9036: "eneo_error_9036", // MCP_UPSTREAM_ERROR
  9037: "eneo_error_9037", // MCP_UPSTREAM_AUTH_ERROR
  9017: "eneo_error_9017", // NAME_COLLISION
  // AI service errors
  9008: "eneo_error_9008", // QUOTA_EXCEEDED
  9010: "eneo_error_9010", // OPENAI_ERROR
  9011: "eneo_error_9011", // CLAUDE_ERROR
  // Internal errors
  9024: "eneo_error_9024", // INTERNAL_SERVER_ERROR
  9038: "eneo_error_9038", // RESOURCE_NOT_READY
  // Model lifecycle
  9039: "eneo_error_9039" // MODEL_IN_USE
};

/**
 * Resolves a user-facing message for any error.
 *
 * Resolution order: mapped backend error code → localized message; unmapped
 * backend error → backend's (English) message; anything else → generic
 * "request failed" fallback.
 */
export function getErrorMessage(error: unknown, t: (key: string) => string): string {
  if (error instanceof EneoApiError) {
    const key = error.code !== undefined ? ERROR_MESSAGE_KEYS[error.code] : undefined;
    if (key) return t(key);
    if (error.message) return error.message;
  }
  return t("request_failed");
}
