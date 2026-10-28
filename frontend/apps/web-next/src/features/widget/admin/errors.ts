import { EneoApiError } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import { blockerLabel } from "./blockers";

type Translate = (key: string, values?: Record<string, string | number>) => string;

/**
 * The widget API answers with `detail: { code, message, … }`. The generic
 * error mapper only knows the backend's numeric codes, so these string codes
 * would surface as raw English; this is where they become the editor's
 * language.
 */
export function widgetErrorCode(error: unknown): string | null {
  return error instanceof EneoApiError && error.reason ? error.reason : null;
}

function detail(error: unknown): Record<string, unknown> | null {
  if (!(error instanceof EneoApiError)) return null;
  const value = error.details;
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
  switch (widgetErrorCode(error)) {
    case "widget_policy_violation":
      return codes(body?.violations);
    case "widget_serving_blocked":
      return codes(body?.blockers);
    case "template_locks_unenforceable":
      return codes(body?.violations);
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

function refusedValueMessage(path: string, t: Translate): string {
  switch (path) {
    case "name":
      return t("widget_admin_name_required");
    case "allowed_origins":
      return t("widget_admin_origins_refused");
    case "texts.suggested_questions":
      return t("widget_admin_questions_refused");
    case "texts.footer_link_url":
    case "theme.logo_url":
      return t("widget_admin_url_invalid");
    default:
      return t("widget_admin_value_refused");
  }
}

/**
 * The fields a failed save is pinned to, as `group` or `group.field` paths,
 * each with a message for that field. Empty when the failure is not about a
 * value the editor can change (network, permissions, an unpublished assistant).
 */
export function widgetFieldErrors(error: unknown, t: Translate): Record<string, string> {
  const fields: Record<string, string> = {};
  for (const code of refusalCodes(error)) {
    const path = CODE_FIELDS[code];
    if (path) fields[path] ??= blockerLabel(code, t);
  }
  if (error instanceof EneoApiError && error.status === 422) {
    const items = error.details;
    for (const item of Array.isArray(items) ? items : []) {
      const loc: unknown[] = Array.isArray(item?.loc) ? item.loc : [];
      const [where, key, field] = loc;
      if (where !== "body" || typeof key !== "string" || key === "revision") continue;
      const path = typeof field === "string" ? `${key}.${field}` : key;
      fields[path] ??= refusedValueMessage(path, t);
    }
  }
  return fields;
}

export function widgetErrorMessage(error: unknown, t: Translate): string | null {
  const reasons = () =>
    refusalCodes(error)
      .map((code) => blockerLabel(code, t))
      .join(" ");
  switch (widgetErrorCode(error)) {
    case "field_locked_by_template":
      return t("widget_admin_error_field_locked");
    case "template_not_published":
      return t("widget_admin_error_template_not_published");
    case "template_in_use":
      return t("widget_admin_template_in_use");
    case "widget_revision_conflict":
      return t("widget_admin_save_conflict");
    case "widget_policy_violation":
      return t("widget_admin_error_policy_violation", { reasons: reasons() });
    case "widget_serving_blocked":
      return t("widget_admin_error_serving_blocked", { reasons: reasons() });
    case "template_locks_unenforceable":
      return t("widget_admin_error_template_locks", { reasons: reasons() });
  }
  if (error instanceof EneoApiError && error.status === 422) {
    if (Object.keys(widgetFieldErrors(error, t)).length > 0) {
      return t("widget_admin_error_values_refused");
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
  if (error instanceof EneoApiError && error.status === 409) return true;
  return widgetErrorCode(error) === "field_locked_by_template";
}

/** Toast a widget API error in the editor's language, falling back to the generic mapper. */
export function toastWidgetError(error: unknown, t: Translate): void {
  const known = widgetErrorMessage(error, t);
  if (known) toast.error(known);
  else toastApiError(error, t);
}
