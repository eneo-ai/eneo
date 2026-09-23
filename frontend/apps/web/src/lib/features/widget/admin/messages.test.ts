import { describe, expect, it } from "vitest";
import en from "../../../../../messages/en.json";
import sv from "../../../../../messages/sv.json";

const catalogs = { en, sv } as Record<string, Record<string, string>>;

describe.each(Object.entries(catalogs))("widget admin copy (%s)", (_locale, messages) => {
  // WCAG 2.5.3: a voice-control user says what the link shows.
  it("starts the overview link's accessible name with its visible text", () => {
    expect(messages.widget_admin_overview_open.startsWith(messages.widget_admin_open)).toBe(true);
  });
});
