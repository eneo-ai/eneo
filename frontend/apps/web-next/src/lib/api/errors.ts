/**
 * Normalized error handling for backend API calls. Every failed request — on
 * the server (eneoApi) or in the browser (browserApi) — is surfaced as an
 * EneoApiError carrying the HTTP status, the backend error code, a readable
 * message and the backend's correlation ids for the failing request.
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
  /** Specific backend failure identifier (`code` on GeneralError). */
  readonly reason?: string;
  /** Trace id of the failing request, for correlation with backend logs. */
  readonly traceId?: string;
  /** Backend error id for unexpected failures, for correlation with backend logs. */
  readonly errorId?: string;
  /** Structured error payload (`details` on GeneralError), when present. */
  readonly details?: unknown;

  constructor(
    message: string,
    options: {
      status: number;
      code?: number;
      reason?: string;
      traceId?: string;
      errorId?: string;
      details?: unknown;
    }
  ) {
    super(message);
    this.name = "EneoApiError";
    this.status = options.status;
    this.code = options.code;
    this.reason = options.reason;
    this.traceId = options.traceId;
    this.errorId = options.errorId;
    this.details = options.details;
  }
}

/**
 * The ids a user quotes to support for a failed request: the backend's
 * `error_id` (an unexpected 500 asks for it) and the request's trace id. Both
 * when present; neither for an error that did not come from the backend.
 */
export function errorReference(error: unknown): { errorId?: string; traceId?: string } {
  if (!(error instanceof EneoApiError)) return {};
  return {
    ...(error.errorId ? { errorId: error.errorId } : {}),
    ...(error.traceId ? { traceId: error.traceId } : {})
  };
}

/** `errorReference` as labelled lines ("Fel-ID: …", "Spårnings-ID: …") for every error display. */
export function errorReferenceLines(error: unknown, t: (key: string) => string): string[] {
  const { errorId, traceId } = errorReference(error);
  return [
    errorId ? `${t("error_id")}: ${errorId}` : null,
    traceId ? `${t("trace_id")}: ${traceId}` : null
  ].filter((line): line is string => line !== null);
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
 *  4. Unexpected failure (500): `{ message, error_id, ... }`
 */
function parseErrorBody(body: unknown): {
  message?: string;
  code?: number;
  reason?: string;
  errorId?: string;
  details?: unknown;
} {
  if (!isRecord(body)) return {};

  if (typeof body.message === "string") {
    return {
      message: body.message,
      code: typeof body.eneo_error_code === "number" ? body.eneo_error_code : undefined,
      reason: typeof body.code === "string" ? body.code : undefined,
      errorId: typeof body.error_id === "string" ? body.error_id : undefined,
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

/**
 * Reads the backend error code from a failed response without consuming the
 * body (clones). Returns undefined for non-JSON bodies or unknown shapes.
 */
export async function errorCodeFromResponse(response: Response): Promise<number | undefined> {
  try {
    return parseErrorBody(await response.clone().json()).code;
  } catch {
    return undefined;
  }
}

export function apiErrorFromResponse(response: Response, body: unknown): EneoApiError {
  const { message, code, reason, errorId, details } = parseErrorBody(body);
  return new EneoApiError(message ?? `Request failed with status ${response.status}`, {
    status: response.status,
    code,
    reason,
    traceId: extractTraceId(response.headers),
    errorId,
    details
  });
}

const FINAL_STATUSES = new Set([401, 403, 404, 410]);

/**
 * A refusal that asking again won't change: signed out (401), forbidden (403)
 * or gone (404, 410). A conflict, a rate limit or a network error passes.
 */
export function isFinalError(error: unknown): boolean {
  return error instanceof EneoApiError && FINAL_STATUSES.has(error.status);
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
 * key to src/lib/i18n/extra/{en,sv}.json (or the Svelte catalogs), run
 * `bun run i18n:convert`, and add the entry below.
 */
const ERROR_MESSAGE_KEYS: Record<number, string> = {
  // Authorization & authentication
  9001: "eneo_error_9001", // UNAUTHORIZED
  9005: "eneo_error_9005", // AUTHENTICATION_ERROR
  9019: "eneo_error_9019", // USER_INACTIVE
  9025: "eneo_error_9025", // TENANT_SUSPENDED
  9058: "eneo_error_9058", // PASSWORD_REUSE
  9059: "eneo_error_9059", // PASSWORD_POLICY_VIOLATION
  9060: "eneo_error_9060", // LOCAL_PASSWORD_CHANGE_UNAVAILABLE
  9061: "eneo_error_9061", // CURRENT_PASSWORD_INCORRECT
  9070: "eneo_error_9070", // PASSWORD_CHANGE_REQUIRED
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
  9039: "eneo_error_9039", // MODEL_IN_USE
  // Icons
  9075: "eneo_error_9075", // ICON_IN_USE
  9076: "eneo_error_9076", // ICON_NOT_ATTACHABLE
  // Governance
  9069: "eneo_error_9069", // PROMPT_IN_USE_BY_GOVERNANCE
  // Skill lifecycle
  9048: "eneo_error_9048", // SKILL_SLUG_CONFLICT
  9049: "eneo_error_9049", // SKILL_PUBLISHED_DELETE_FORBIDDEN
  9050: "eneo_error_9050", // SKILL_USED_BY_APP_RUN
  9051: "eneo_error_9051", // SKILL_STILL_ATTACHED
  9052: "eneo_error_9052" // SKILL_EXECUTION_BLOCK_CONFLICT
};

/**
 * Resolves a user-facing message for any error.
 *
 * Resolution order: mapped backend error code → localized message; an
 * unexpected failure (error id, no code) → localized "error occurred";
 * other backend error → backend's (English) message; anything else → generic
 * "request failed" fallback.
 */
/**
 * An integration refusal names its cause in the payload's `code`. A Microsoft
 * error code (AADSTS…) in the backend's message is kept: an administrator looks
 * it up.
 */
const INTEGRATION_FAILURE_MESSAGES: Record<string, (t: (key: string) => string) => string> = {
  sharepoint_credentials_invalid: (t) => t("integration_error_credentials_invalid"),
  oauth_code_rejected: (t) => t("integration_error_oauth_code_rejected"),
  oauth_client_rejected: (t) => t("integration_error_oauth_client_rejected"),
  integration_knowledge_syncing: (t) => t("integration_error_syncing")
};
const AADSTS_CODE = /\bAADSTS\d+\b/;

function getIntegrationFailureMessage(
  error: EneoApiError,
  t: (key: string) => string
): string | null {
  const describe = error.reason ? INTEGRATION_FAILURE_MESSAGES[error.reason] : undefined;
  if (!describe) return null;
  const microsoft = AADSTS_CODE.exec(error.message)?.[0];
  return microsoft ? `${describe(t)} (${microsoft})` : describe(t);
}

export function getErrorMessage(error: unknown, t: (key: string) => string): string {
  if (error instanceof EneoApiError) {
    const message = getIntegrationFailureMessage(error, t) ?? getErrorMessageForCode(error.code, t);
    if (message) return message;
    // An unexpected failure (500 body: error_id, no code) carries a generic
    // English sentence; the error id it asks for is shown by errorReference.
    if (error.errorId !== undefined && error.code === undefined) return t("error_occurred");
    if (error.message) return error.message;
  }
  return t("request_failed");
}

/** Resolve a backend error code without needing a full EneoApiError instance. */
export function getErrorMessageForCode(
  code: number | null | undefined,
  t: (key: string) => string
): string | null {
  if (code !== undefined && code !== null) {
    const key = ERROR_MESSAGE_KEYS[code];
    if (key) return t(key);
  }
  return null;
}
