import type { Widget, WidgetPolicy } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";

// The API's defaults for settings a widget has never saved (WidgetLimits, WidgetPrivacy).
const DEFAULT_DAILY_TOKEN_BUDGET = 500_000;
const DEFAULT_RETENTION_DAYS = 30;

/** Human-readable explanation of an activation blocker code from the API. */
export function blockerLabel(code: string): string {
  switch (code) {
    case "allowed_origins_empty":
      return m.widget_admin_blocker_allowed_origins_empty();
    case "subtitle_empty":
      return m.widget_admin_blocker_subtitle_empty();
    case "subtitle_required_for_legal_texts_lock":
      return m.widget_admin_blocker_legal_texts_lock_subtitle();
    case "target_not_published":
      return m.widget_admin_blocker_target_not_published();
    case "archived":
      return m.widget_admin_blocker_archived();
    case "daily_token_budget_exceeds_policy":
      return m.widget_admin_blocker_budget_policy();
    case "retention_below_policy_minimum":
      return m.widget_admin_blocker_retention_min();
    case "retention_above_policy_maximum":
      return m.widget_admin_blocker_retention_max();
    case "bot_protection_none_not_allowed":
      return m.widget_admin_blocker_bot_protection();
    default:
      return code;
  }
}

/**
 * The tenant policy codes a widget breaks, as the API checks them before it
 * activates (backend `WidgetPolicy.violations`). They are not part of
 * `activation_blockers`, which only covers the widget and its assistant.
 */
export function policyViolations(widget: Widget, policy: WidgetPolicy | null): string[] {
  if (!policy) return [];
  const violations: string[] = [];
  const budget = widget.limits.daily_token_budget ?? DEFAULT_DAILY_TOKEN_BUDGET;
  const retention = widget.privacy.retention_days ?? DEFAULT_RETENTION_DAYS;
  if (budget > policy.max_daily_token_budget) violations.push("daily_token_budget_exceeds_policy");
  if (retention < policy.min_retention_days) violations.push("retention_below_policy_minimum");
  if (retention > policy.max_retention_days) violations.push("retention_above_policy_maximum");
  if (widget.bot_protection === "none" && !policy.allow_bot_protection_none) {
    violations.push("bot_protection_none_not_allowed");
  }
  return violations;
}
