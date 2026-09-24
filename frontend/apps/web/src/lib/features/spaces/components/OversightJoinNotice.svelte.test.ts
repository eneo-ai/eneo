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

import OversightJoinNotice from "./OversightJoinNotice.svelte";

const JOINED_AT = "2026-09-20T09:30:00Z";
const dateText = new Intl.DateTimeFormat("sv-SE", { dateStyle: "medium" }).format(
  new Date(JOINED_AT)
);

const viewer = { id: "u1", email: "vera@example.org", username: "Vera", role: "viewer" as const };
const overseer = {
  id: "u2",
  email: "olle@example.org",
  username: null,
  role: "editor" as const,
  oversight_join: { joined_at: JOINED_AT, reason: null }
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
    render(OversightJoinNotice, { members: [viewer] });
    expect(notice().elements()).toHaveLength(0);
    expect(document.body.textContent).not.toContain("space_oversight");
  });

  test("tells every member who joined, when and with which role, without a reason they may not see", async () => {
    render(OversightJoinNotice, { members: [viewer, overseer] });

    await expect.element(notice()).toHaveAccessibleName("space_oversight_notice_title");
    await expect
      .element(notice())
      .toHaveTextContent(
        `space_oversight_notice_item(olle@example.org|${dateText}|space_role_editor)`
      );
    expect(notice().element().textContent).not.toContain("space_oversight_notice_reason");
    // A standing notice on the page: no alert, no live region and no extra heading.
    expect(notice().element().closest("[role=alert], [aria-live]")).toBeNull();
    expect(notice().element().querySelector("h1, h2, h3, h4, h5, h6")).toBeNull();
  });

  test("shows the reason when the member may read it, and names several administrators", async () => {
    render(OversightJoinNotice, {
      members: [
        { ...overseer, oversight_join: { joined_at: JOINED_AT, reason: "Ärende 2026-114" } },
        {
          id: "u3",
          email: "ada@example.org",
          username: "Ada",
          role: "admin",
          oversight_join: { joined_at: JOINED_AT, reason: null }
        }
      ]
    });

    await expect.element(notice()).toHaveAccessibleName("space_oversight_notice_title_many");
    const items = page.getByRole("listitem").elements();
    expect(items).toHaveLength(2);
    expect(items[0].textContent).toContain("space_oversight_notice_reason(Ärende 2026-114)");
    expect(items[1].textContent).toContain(`space_oversight_notice_item(Ada|${dateText}|`);
    expect(items[1].textContent).not.toContain("space_oversight_notice_reason");
  });

  test.each(["light", "dark"] as const)(
    "passes every WCAG 2.2 A and AA rule (%s)",
    async (scheme) => {
      document.documentElement.dataset.theme = scheme;
      render(OversightJoinNotice, {
        members: [{ ...overseer, oversight_join: { joined_at: JOINED_AT, reason: "Ärende 12" } }]
      });
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
