import { page } from "@vitest/browser/context";
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

import SecurityClassificationBadge from "./SecurityClassificationBadge.svelte";

const classification = { name: "Konfidentiell", security_level: 2 };

beforeEach(() => {
  delete document.documentElement.dataset.theme;
  // The app shell paints the page; without it dark text is measured on white.
  document.body.classList.add("bg-primary");
});

afterEach(() => document.body.classList.remove("bg-primary"));

describe("SecurityClassificationBadge", () => {
  test("reads as the name and level, without a live region or a visible label", async () => {
    render(SecurityClassificationBadge, { classification });

    const badge = document.querySelector<HTMLElement>("[data-slot=badge]")!;
    expect(badge.innerText.replace(/\s+/g, " ").trim()).toBe(
      "Konfidentiell · security_classification_badge_level(2)"
    );
    expect(badge.querySelector("[role=status], [aria-live]")).toBeNull();
    expect(badge.getAttribute("role")).toBeNull();
    expect(badge.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
    expect(badge.querySelector(".sr-only")).toBeNull();
  });

  test("can say what it is to screen readers where nothing around it does", async () => {
    render(SecurityClassificationBadge, { classification, labelled: true });

    await expect.element(page.getByText("security_classification:")).toHaveClass("sr-only");
  });

  test("wraps a long name instead of overflowing a narrow cell", async () => {
    const screen = render(SecurityClassificationBadge, {
      classification: {
        name: "Mycket känsliga personuppgifter enligt artikel 9",
        security_level: 4
      }
    });
    const cell = screen.container as HTMLElement;
    cell.style.width = "120px";

    const badge = cell.querySelector<HTMLElement>("[data-slot=badge]")!;
    expect(badge.getBoundingClientRect().width).toBeLessThanOrEqual(120);
    expect(badge.scrollWidth).toBeLessThanOrEqual(badge.clientWidth + 1);
  });

  test.each(["light", "dark"] as const)(
    "passes every WCAG 2.2 A and AA rule (%s)",
    async (scheme) => {
      document.documentElement.dataset.theme = scheme;
      render(SecurityClassificationBadge, { classification, labelled: true });

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
