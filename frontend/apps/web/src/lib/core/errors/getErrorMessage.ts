import { EneoError, type EneoErrorCode } from "@eneo/eneo-js";
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
 * Error codes are defined in: backend/src/eneo/main/exceptions.py → ErrorCodes enum
 * The @unique decorator on ErrorCodes guarantees no duplicate codes exist.
 */
/**
 * The reviewed execution block was released or replaced before this unblock was
 * applied. Exported because the recovery — re-read the block and show the live
 * state — is a decision, not just a message.
 */
export const SKILL_EXECUTION_BLOCK_CONFLICT: EneoErrorCode = 9052;

// Keyed on the generated code union, so a code the backend does not define
// fails to compile instead of mapping a message nothing can ever reach.
const ERROR_CODE_MESSAGES: Partial<Record<EneoErrorCode, () => string>> = {
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
  9017: () => m.eneo_error_9017(), // NAME_COLLISION (duplicate display name)
  9042: () => m.eneo_error_9042(), // ENCRYPTION_NOT_CONFIGURED

  // --- AI service errors ---
  9008: () => m.eneo_error_9008(), // QUOTA_EXCEEDED
  9010: () => m.eneo_error_9010(), // OPENAI_ERROR
  9011: () => m.eneo_error_9011(), // CLAUDE_ERROR

  // --- Internal errors ---
  9024: () => m.eneo_error_9024(), // INTERNAL_SERVER_ERROR
  9038: () => m.eneo_error_9038(), // RESOURCE_NOT_READY

  // --- File uploads ---
  9056: () => m.eneo_error_9056(), // INVALID_FILENAME

  // --- Model lifecycle ---
  9039: () => m.eneo_error_9039(), // MODEL_IN_USE

  // --- Concurrent changes ---
  9043: () => m.eneo_error_9043(), // SKILL_REVISION_CONFLICT
  9052: () => m.eneo_error_9052(), // SKILL_EXECUTION_BLOCK_CONFLICT
  9055: () => m.eneo_error_9055(), // SKILL_RUNTIME_POLICY_CHANGED

  // --- Skill lifecycle ---
  9048: () => m.eneo_error_9048(), // SKILL_SLUG_TAKEN
  9049: () => m.eneo_error_9049(), // SKILL_PUBLISHED_NOT_DELETABLE
  9050: () => m.eneo_error_9050(), // SKILL_IN_USE_BY_APP_RUN
  9051: () => m.eneo_error_9051(), // SKILL_STILL_ATTACHED
  9053: () => m.eneo_error_9053(), // SKILL_NOT_PUBLISHED_FOR_BINDING
  9054: () => m.eneo_error_9054() // SKILL_BLOCKED_FOR_BINDING
};

/**
 * Get a localized, user-facing error message from any error.
 *
 * Resolution order:
 * 1. Eneo backend error with a mapped error code → localized i18n message
 * 2. Eneo backend error without mapping → backend's readable message (English fallback)
 * 3. Other errors → `fallback`, or the generic "Something went wrong"
 *
 * Pass `fallback` when the call site knows what failed — "The Skill could not be
 * deleted" beats "Something went wrong" for a network error or a thrown string.
 * Writing `getErrorMessage(error) || specific()` does not work: this never
 * returns an empty string, so that branch is dead.
 *
 * Use toastError() to show the message directly as a toast notification.
 */
export function getErrorMessage(error: unknown, fallback?: string): string {
  if (error instanceof EneoError) {
    const mapped = ERROR_CODE_MESSAGES[error.code];
    if (mapped) {
      return mapped();
    }
    const readable = error.getReadableMessage();
    if (readable) {
      return readable;
    }
  }
  return fallback ?? m.request_failed();
}
