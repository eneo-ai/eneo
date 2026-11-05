/* eslint-disable eneo/no-raw-color -- fixtures use literal widget colours */
import type { WidgetTemplate } from "../autosave";
import type { WidgetPolicy } from "../queries";
import type { WidgetOverviewItem } from "./queries";

export const texts = {
  title: "Fråga oss",
  welcome: "Hej!",
  placeholder: "",
  suggested_questions: [],
  subtitle: "Du chattar med en AI-assistent.",
  footer_text: "",
  footer_link_url: null,
  footer_link_label: ""
};

export const release = {
  texts,
  theme: { primary_color: "#1F4E79", radius: 12 },
  persona: { name: "", avatar_icon_id: null, avatar_in_launcher: false },
  language: "sv" as const,
  locked_groups: ["appearance", "language"] as WidgetTemplate["locked_groups"]
};

export function template(overrides: Partial<WidgetTemplate> = {}): WidgetTemplate {
  return {
    id: "t1",
    name: "Kommunmallen",
    description: "",
    ...release,
    is_default: false,
    linked_widgets: 3,
    published_at: "2026-09-21T10:00:00Z",
    published_by_user_id: null,
    published: release,
    has_unpublished_changes: false,
    created_at: "2026-09-21T10:00:00Z",
    updated_at: "2026-09-21T10:00:00Z",
    ...overrides
  } as WidgetTemplate;
}

export const policy: WidgetPolicy = {
  max_daily_token_budget: 1000,
  min_retention_days: 0,
  max_retention_days: 365,
  allow_bot_protection_none: false
};

export function overviewItem(overrides: Partial<WidgetOverviewItem> = {}): WidgetOverviewItem {
  return {
    id: "w1",
    public_id: "wgt_aaaaaaaaaaaaaaaaaaaaaa",
    name: "Kontaktchatt",
    status: "active",
    space_id: "s1",
    space_name: "Kundtjänst",
    target_id: "a1",
    assistant_name: "Kontakt",
    allowed_origins: ["https://www.kommun.se"],
    activation_blockers: [],
    updated_at: "2026-10-28T08:00:00Z",
    daily_token_budget: 1000,
    budget_used_today: 0,
    questions_7d: 0,
    questions_30d: 0,
    input_tokens_30d: 0,
    output_tokens_30d: 0,
    blocked_30d: 0,
    helpful_30d: 0,
    unhelpful_30d: 0,
    last_activity: null,
    ...overrides
  };
}

export function overview(
  items: WidgetOverviewItem[],
  active = items.filter((i) => i.status === "active").length
) {
  return {
    items,
    totals: {
      widgets: items.length,
      active,
      questions_7d: 0,
      questions_30d: 0,
      tokens_30d: 0,
      blocked_30d: 0,
      helpful_30d: 0,
      unhelpful_30d: 0
    }
  };
}
