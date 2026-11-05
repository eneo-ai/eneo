type Translate = (key: string, values?: Record<string, string | number>) => string;

/** Human-readable explanation of an activation blocker code from the API. */
export function blockerLabel(code: string, t: Translate): string {
  switch (code) {
    case "allowed_origins_empty":
      return t("widget_admin_blocker_allowed_origins_empty");
    case "subtitle_empty":
      return t("widget_admin_blocker_subtitle_empty");
    case "subtitle_required_for_legal_texts_lock":
      return t("widget_admin_blocker_legal_texts_lock_subtitle");
    case "target_not_published":
      return t("widget_admin_blocker_target_not_published");
    case "organization_space_unsupported":
      return t("widget_admin_blocker_organization_space_unsupported");
    case "personal_space_unsupported":
      return t("widget_admin_blocker_personal_space_unsupported");
    case "archived":
      return t("widget_admin_blocker_archived");
    case "daily_token_budget_exceeds_policy":
      return t("widget_admin_blocker_budget_policy");
    case "retention_below_policy_minimum":
      return t("widget_admin_blocker_retention_min");
    case "retention_above_policy_maximum":
      return t("widget_admin_blocker_retention_max");
    case "bot_protection_none_not_allowed":
      return t("widget_admin_blocker_bot_protection");
    default:
      return code;
  }
}
