import { describe, expect, it } from "vitest";
import en from "../../../../../messages/en.json";
import sv from "../../../../../messages/sv.json";

const catalogs = { en, sv } as Record<string, Record<string, string>>;

describe.each(Object.entries(catalogs))("widget admin copy (%s)", (_locale, messages) => {
  // WCAG 2.5.3: a voice-control user says what the link shows.
  it("starts the review link's accessible name with its visible text", () => {
    expect(
      messages.widget_admin_overview_review_named.startsWith(messages.widget_admin_overview_review)
    ).toBe(true);
  });

  it("sends an editor without allowed websites to a tab that exists", () => {
    expect(messages.widget_admin_blocker_allowed_origins_empty).toContain(
      messages.widget_admin_tab_rules
    );
  });
});
