import { IntricError } from "@intric/intric-js";
import { m } from "$lib/paraglide/messages";

/**
 * Maps backend error codes to localized i18n messages.
 *
 * IMPORTANT: When adding a new error code in the backend, you MUST also:
 *
 * 1. Add the i18n key in BOTH language files:
 *    - messages/en.json → "eneo_error_{code}": "English message"
 *    - messages/sv.json → "eneo_error_{code}": "Swedish message"
 *
 * 2. Add the mapping below:
 *    {code}: () => m.eneo_error_{code}()
 *
 * If step 1 or 2 is skipped, the error will fall back to the backend's
 * English message — functional, but not localized.
 *
 * Error codes are defined in: backend/src/intric/main/exceptions.py → ErrorCodes enum
 * The @unique decorator on ErrorCodes guarantees no duplicate codes exist.
 */
const ERROR_CODE_MESSAGES: Record<number, () => string> = {
  // --- Authorization & authentication ---
  9001: () => m.eneo_error_9001(), // UNAUTHORIZED
  9005: () => m.eneo_error_9005(), // AUTHENTICATION_ERROR
  9019: () => m.eneo_error_9019(), // USER_INACTIVE
  9025: () => m.eneo_error_9025(), // TENANT_SUSPENDED

  // --- Model & provider issues ---
  9002: () => m.eneo_error_9002(), // UNSUPPORTED_MODEL
  9020: () => m.eneo_error_9020(), // NO_MODEL_SELECTED
  9026: () => m.eneo_error_9026(), // API_KEY_NOT_CONFIGURED
  9031: () => m.eneo_error_9031(), // PROVIDER_INACTIVE
  9033: () => m.eneo_error_9033(), // MODEL_NOT_AVAILABLE
  9034: () => m.eneo_error_9034(), // KNOWLEDGE_MODEL_UNAVAILABLE
  9035: () => m.eneo_error_9035(), // SECURITY_CLASSIFICATION_MISMATCH
  9036: () => m.eneo_error_9036(), // MCP_UPSTREAM_ERROR
  9037: () => m.eneo_error_9037(), // MCP_UPSTREAM_AUTH_ERROR

  // --- AI service errors ---
  9008: () => m.eneo_error_9008(), // QUOTA_EXCEEDED
  9010: () => m.eneo_error_9010(), // OPENAI_ERROR
  9011: () => m.eneo_error_9011(), // CLAUDE_ERROR

  // --- Internal errors ---
  9024: () => m.eneo_error_9024(), // INTERNAL_SERVER_ERROR
  9038: () => m.eneo_error_9038() // RESOURCE_NOT_READY
};

/**
 * Get a localized, user-facing error message from any error.
 *
 * Resolution order:
 * 1. Eneo backend error with a mapped error code → localized i18n message
 * 2. Eneo backend error without mapping → backend's readable message (English fallback)
 * 3. Other errors → generic localized fallback ("Something went wrong")
 *
 * Use toastError() to show the message directly as a toast notification.
 */
export function getErrorMessage(error: unknown): string {
  if (error instanceof IntricError) {
    const mapped = ERROR_CODE_MESSAGES[error.code];
    if (mapped) {
      return mapped();
    }
    const readable = error.getReadableMessage();
    if (readable) {
      return readable;
    }
  }
  return m.request_failed();
}
