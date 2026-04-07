import { toast } from "$lib/components/toast";
import { getErrorMessage } from "./getErrorMessage";

/**
 * Show a localized error toast for any error.
 *
 * Uses the centralized error code → i18n mapping from getErrorMessage().
 *
 * @param error - The caught error (backend error, Error, or unknown)
 * @param context - Optional operation context, e.g. m.could_not_delete_assistant()
 *
 * @example
 * // Simple — shows the localized backend error
 * toastError(error);
 *
 * // With context — "Could not delete assistant: You do not have permission"
 * toastError(error, m.could_not_delete_assistant());
 */
export function toastError(error: unknown, context?: string): void {
  const message = getErrorMessage(error);
  toast.error(context ? `${context}: ${message}` : message);
}
