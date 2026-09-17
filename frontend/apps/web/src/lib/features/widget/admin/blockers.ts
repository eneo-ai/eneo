import { m } from "$lib/paraglide/messages";

/** Human-readable explanation of an activation blocker code from the API. */
export function blockerLabel(code: string): string {
  switch (code) {
    case "allowed_origins_empty":
      return m.widget_admin_blocker_allowed_origins_empty();
    case "subtitle_empty":
      return m.widget_admin_blocker_subtitle_empty();
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
