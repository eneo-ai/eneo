import { EneoError } from "@eneo/eneo-js";
import { toast } from "$lib/components/toast";
import { toastError } from "$lib/core/errors";
import { m } from "$lib/paraglide/messages";

/**
 * The widget API answers with `detail: { code, message }`. The generic error
 * mapper only knows the backend's numeric codes, so these string codes would
 * surface as raw English; this is where they become the editor's language.
 */
export function widgetErrorCode(error: unknown): string | null {
  if (!(error instanceof EneoError)) return null;
  const detail = (error.response as { detail?: { code?: unknown } } | undefined)?.detail;
  return typeof detail?.code === "string" ? detail.code : null;
}

export function widgetErrorMessage(error: unknown): string | null {
  switch (widgetErrorCode(error)) {
    case "field_locked_by_template":
      return m.widget_admin_error_field_locked();
    case "template_not_published":
      return m.widget_admin_error_template_not_published();
    case "template_in_use":
      return m.widget_admin_template_in_use();
    case "widget_revision_conflict":
      return m.widget_admin_save_conflict();
    default:
      return null;
  }
}

/**
 * Errors after which the editor's copy is stale and must be reloaded: a
 * revision conflict, or a lock that was published while the field looked
 * editable here.
 */
export function isStaleEditorError(error: unknown): boolean {
  if (error instanceof EneoError && error.status === 409) return true;
  return widgetErrorCode(error) === "field_locked_by_template";
}

/** Toast a widget API error in the editor's language, falling back to the generic mapper. */
export function toastWidgetError(error: unknown, context: string): void {
  const known = widgetErrorMessage(error);
  if (known) toast.error(known);
  else toastError(error, context);
}
