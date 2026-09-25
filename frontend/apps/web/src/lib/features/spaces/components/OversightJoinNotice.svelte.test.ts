import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import "../../../../app.css";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy(
    {},
    {
      get: (_target, key) => (params?: Record<string, unknown>) =>
        params ? `${String(key)}(${Object.values(params).join("|")})` : String(key)
    }
  )
}));
vi.mock("$lib/paraglide/runtime", () => ({ getLocale: () => "sv" }));

import type { SpaceOversightVisit } from "@eneo/eneo-js";
import OversightJoinNotice from "./OversightJoinNotice.svelte";

const JOINED_AT = "2026-09-20T09:30:00Z";
const LEFT_AT = "2026-09-21T15:00:00Z";
const day = (value: string) =>
  new Intl.DateTimeFormat("sv-SE", { dateStyle: "medium" }).format(new Date(value));

const open: SpaceOversightVisit = {
  person: { id: "u2", name: "olle@example.org" },
  role: "editor",
  joined_at: JOINED_AT,
  left_at: null,
  reason: null
};
const ended: SpaceOversightVisit = {
  person: { id: "u3", name: "Ada" },
  role: "viewer",
  joined_at: JOINED_AT,
  left_at: LEFT_AT,
  reason: null
};

const notice = () => page.getByRole("note");

beforeEach(() => {
  delete document.documentElement.dataset.theme;
  document.body.classList.add("bg-primary");
});

afterEach(() => {
  document.body.classList.remove("bg-primary");
});

describe("OversightJoinNotice", () => {
  test("stays away while nobody joined through oversight", async () => {
    render(OversightJoinNotice, { visits: [] });
    expect(notice().elements()).toHaveLength(0);
    expect(document.body.textContent).not.toContain("space_oversight");
  });

  test("tells every member who joined, when and with which role, without a reason they may not see", async () => {
    render(OversightJoinNotice, { visits: [open] });

    await expect.element(notice()).toHaveAccessibleName("space_oversight_notice_title");
    await expect.element(notice()).toHaveTextContent("space_oversight_notice_help");
    await expect
      .element(notice())
      .toHaveTextContent(
        `space_oversight_visit_open(olle@example.org|${day(JOINED_AT)}|space_role_editor)`
      );
    expect(notice().element().textContent).not.toContain("space_oversight_notice_reason");
    // A standing notice on the page: no alert, no live region and no extra heading.
    expect(notice().element().closest("[role=alert], [aria-live]")).toBeNull();
    expect(notice().element().querySelector("h1, h2, h3, h4, h5, h6")).toBeNull();
  });

  test("keeps a visit that has ended, with when the administrator left", async () => {
    render(OversightJoinNotice, { visits: [ended] });

    await expect
      .element(notice())
      .toHaveTextContent(
        `space_oversight_visit_left(Ada|${day(JOINED_AT)}|space_role_viewer|${day(LEFT_AT)})`
      );
  });

  test("names a deleted administrator neutrally and counts people, not visits", async () => {
    const again = { ...open, joined_at: "2026-09-10T08:00:00Z", left_at: "2026-09-11T08:00:00Z" };
    const { rerender } = render(OversightJoinNotice, { visits: [open, again] });
    // One person, two visits.
    await expect.element(notice()).toHaveAccessibleName("space_oversight_notice_title");
    expect(page.getByRole("listitem").elements()).toHaveLength(2);

    await rerender({ visits: [open, { ...ended, person: null }] });
    await expect.element(notice()).toHaveAccessibleName("space_oversight_notice_title_many");
    expect(page.getByRole("listitem").elements()[1].textContent).toContain(
      "space_oversight_visit_left(space_oversight_visit_deleted_person|"
    );
  });

  test("shows the reason when the member may read it", async () => {
    render(OversightJoinNotice, {
      visits: [{ ...open, reason: "Ärende 2026-114" }, ended]
    });

    const items = page.getByRole("listitem").elements();
    expect(items).toHaveLength(2);
    expect(items[0].textContent).toContain("space_oversight_notice_reason(Ärende 2026-114)");
    expect(items[1].textContent).not.toContain("space_oversight_notice_reason");
  });

  test.each(["light", "dark"] as const)(
    "passes every WCAG 2.2 A and AA rule (%s)",
    async (scheme) => {
      document.documentElement.dataset.theme = scheme;
      render(OversightJoinNotice, { visits: [{ ...open, reason: "Ärende 12" }, ended] });
      await expect.element(notice()).toBeVisible();
      await userEvent.unhover(document.body);

      const result = await axe.run(document, {
        runOnly: {
          type: "tag",
          values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"]
        },
        rules: { "landmark-one-main": { enabled: false }, region: { enabled: false } }
      });
      expect(result.violations.map((violation) => violation.id)).toEqual([]);
    }
  );
});
