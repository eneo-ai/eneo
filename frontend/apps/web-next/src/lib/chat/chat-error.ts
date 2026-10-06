import { EneoApiError, getErrorMessageForCode } from "@/lib/api/errors";

type Translate = (key: string, values?: Record<string, string | number>) => string;

/** What the chat shows when a question fails. */
export type ChatFailure = {
  /** One human sentence: shown in the conversation and announced. */
  message: string;
  /**
   * Technical lines for support (HTTP status, backend code, the backend's
   * own message, trace id), kept behind a disclosure. Empty when the sentence
   * already says everything there is to know.
   */
  details: string[];
};

/** Longer backend text is cut so a stack trace or HTML page never fills the chat. */
const DETAIL_MAX_LENGTH = 300;

/**
 * The AI SDK turns a refused response into `new Error(await response.text())`
 * and the backend's `error` stream part into `new Error(errorText)`, so a raw
 * JSON body can arrive as an error message. Pull the message and code out of
 * it; anything unparseable stays as it is.
 */
function parseJsonMessage(text: string): { message?: string; code?: number } | null {
  const trimmed = text.trim();
  if (!trimmed.startsWith("{")) return null;
  try {
    const body: unknown = JSON.parse(trimmed);
    if (typeof body !== "object" || body === null) return null;
    const record = body as Record<string, unknown>;
    const detail = record.detail;
    const message =
      typeof record.message === "string"
        ? record.message
        : typeof detail === "string"
          ? detail
          : typeof detail === "object" &&
              detail !== null &&
              typeof (detail as Record<string, unknown>).message === "string"
            ? ((detail as Record<string, unknown>).message as string)
            : undefined;
    const code = typeof record.eneo_error_code === "number" ? record.eneo_error_code : undefined;
    return { message, code };
  } catch {
    return null;
  }
}

function truncate(text: string): string {
  const line = text.replace(/\s+/g, " ").trim();
  return line.length > DETAIL_MAX_LENGTH ? `${line.slice(0, DETAIL_MAX_LENGTH)}…` : line;
}

/**
 * Lost or broken connection: fetch rejects with a TypeError when the network
 * is gone, the proxy or browser abort with a DOMException, and the transport
 * raises StreamContractError when the answer stream closes before `finish`
 * (matched by name: this module stays free of the transport, which tests
 * replace).
 */
function isConnectionFailure(error: unknown): boolean {
  if (error instanceof Error && error.name === "StreamContractError") return true;
  if (error instanceof TypeError) return true;
  return (
    typeof DOMException !== "undefined" &&
    error instanceof DOMException &&
    ["AbortError", "NetworkError", "TimeoutError"].includes(error.name)
  );
}

function sentenceForStatus(status: number, t: Translate): string {
  if (status === 401) return t("session_expired_please_login_again");
  if (status === 403) return t("chat_error_forbidden");
  if (status === 404) return t("chat_error_not_found");
  if (status === 413) return t("chat_error_too_large");
  if (status === 400 || status === 422) return t("chat_error_invalid");
  if (status === 429) return t("chat_error_rate_limited");
  if (status >= 500) return t("chat_error_server");
  return t("request_failed");
}

/**
 * One human sentence for any failed question, never the backend's raw JSON.
 * Resolution: a known backend error code (from the stream's `data-error`
 * part, the refused response, or a JSON error text) → its catalog sentence;
 * a refused response → a sentence for its HTTP status; a lost connection or
 * broken stream → "connection lost"; anything else → the generic sentence.
 * The technical facts go to `details`, for "Visa detaljer".
 */
export function describeChatFailure(
  error: unknown,
  streamErrorCode: number | null | undefined,
  t: Translate
): ChatFailure {
  if (error instanceof EneoApiError) {
    const code = streamErrorCode ?? error.code;
    const details = [t("chat_error_detail_status", { status: error.status })];
    if (code !== undefined && code !== null) {
      details.push(
        t("chat_error_detail_code", { code: error.reason ? `${code} (${error.reason})` : code })
      );
    }
    const backendMessage = parseJsonMessage(error.message)?.message ?? error.message;
    if (backendMessage) details.push(truncate(backendMessage));
    if (error.traceId) details.push(t("chat_error_detail_trace", { traceId: error.traceId }));
    return {
      message: getErrorMessageForCode(code, t) ?? sentenceForStatus(error.status, t),
      details
    };
  }

  const rawMessage =
    error instanceof Error ? error.message : typeof error === "string" ? error : "";
  const parsed = parseJsonMessage(rawMessage);
  const code = streamErrorCode ?? parsed?.code ?? null;
  const details: string[] = [];
  if (code !== null) details.push(t("chat_error_detail_code", { code }));
  const backendMessage = parsed ? parsed.message : rawMessage;
  if (backendMessage) {
    const name = error instanceof Error && error.name !== "Error" ? `${error.name}: ` : "";
    details.push(truncate(`${name}${backendMessage}`));
  }

  const mapped = getErrorMessageForCode(code, t);
  if (mapped) return { message: mapped, details };
  if (isConnectionFailure(error)) return { message: t("chat_error_connection_lost"), details };
  return { message: t("request_failed"), details };
}
