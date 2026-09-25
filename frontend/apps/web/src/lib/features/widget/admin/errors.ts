import { EneoError } from "@eneo/eneo-js";
import { toast } from "$lib/components/toast";
import { toastError } from "$lib/core/errors";
import { m } from "$lib/paraglide/messages";
import { blockerLabel } from "./blockers";

/**
 * The widget API answers with `detail: { code, message }`. The generic error
 * mapper only knows the backend's numeric codes, so these string codes would
 * surface as raw English; this is where they become the editor's language.
 */
export function widgetErrorCode(error: unknown): string | null {
  const code = detail(error)?.code;
  return typeof code === "string" ? code : null;
}

function detail(error: unknown): Record<string, unknown> | null {
  if (!(error instanceof EneoError)) return null;
  const value = (error.response as { detail?: unknown } | undefined)?.detail;
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function codes(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((code): code is string => typeof code === "string")
    : [];
}

/** The policy violation or activation blocker codes a refusal carries. */
function refusalCodes(error: unknown): string[] {
  const body = detail(error);
  switch (body?.code) {
    case "widget_policy_violation":
      return codes(body.violations);
    case "widget_serving_blocked":
      return codes(body.blockers);
    case "template_locks_unenforceable":
      return codes(body.violations);
    default:
      return [];
  }
}

// Where each violation/blocker code sits in the form, as a field path.
const CODE_FIELDS: Record<string, string> = {
  daily_token_budget_exceeds_policy: "limits.daily_token_budget",
  retention_below_policy_minimum: "privacy.retention_days",
  retention_above_policy_maximum: "privacy.retention_days",
  bot_protection_none_not_allowed: "bot_protection",
  allowed_origins_empty: "allowed_origins",
  subtitle_empty: "texts.subtitle",
  subtitle_required_for_legal_texts_lock: "texts.subtitle"
};

function refusedValueMessage(path: string): string {
  switch (path) {
    case "name":
      return m.widget_admin_name_required();
    case "allowed_origins":
      return m.widget_admin_origins_refused();
    case "texts.suggested_questions":
      return m.widget_admin_questions_refused();
    case "texts.footer_link_url":
    case "theme.logo_url":
      return m.widget_admin_url_invalid();
    default:
      return m.widget_admin_value_refused();
  }
}

/**
 * The fields a failed save is pinned to, as `group` or `group.field` paths,
 * each with a message for that field. Empty when the failure is not about a
 * value the editor can change (network, permissions, an unpublished assistant).
 */
export function widgetFieldErrors(error: unknown): Record<string, string> {
  const fields: Record<string, string> = {};
  for (const code of refusalCodes(error)) {
    const path = CODE_FIELDS[code];
    if (path) fields[path] ??= blockerLabel(code);
  }
  if (error instanceof EneoError && error.status === 422) {
    const items = (error.response as { detail?: unknown } | undefined)?.detail;
    for (const item of Array.isArray(items) ? items : []) {
      const loc: unknown[] = Array.isArray(item?.loc) ? item.loc : [];
      const [where, key, field] = loc;
      if (where !== "body" || typeof key !== "string" || key === "revision") continue;
      const path = typeof field === "string" ? `${key}.${field}` : key;
      fields[path] ??= refusedValueMessage(path);
    }
  }
  return fields;
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
    case "widget_activation_request_missing":
      return m.widget_request_error_missing();
    case "widget_policy_violation":
      return m.widget_admin_error_policy_violation({
        reasons: refusalCodes(error).map(blockerLabel).join(" ")
      });
    case "widget_serving_blocked":
      return m.widget_admin_error_serving_blocked({
        reasons: refusalCodes(error).map(blockerLabel).join(" ")
      });
    case "template_locks_unenforceable":
      return m.widget_admin_error_template_locks({
        reasons: refusalCodes(error).map(blockerLabel).join(" ")
      });
  }
  if (error instanceof EneoError && error.status === 422) {
    if (Object.keys(widgetFieldErrors(error)).length > 0) {
      return m.widget_admin_error_values_refused();
    }
  }
  return null;
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
