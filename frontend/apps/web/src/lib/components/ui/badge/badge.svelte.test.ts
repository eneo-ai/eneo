import { createRawSnippet } from "svelte";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { contrastAgainst } from "$lib/features/widget/components/contrastProbe";
import { Badge } from "./index.js";
import "../../../../app.css";

// Reference component test: renders a real Svelte 5 component in Chromium and
// asserts on the resulting DOM. The `.svelte.test.ts` suffix routes this file to
// the browser-mode "client" Vitest project (see vite.config.ts). Use this as the
// template for testing any component.
const label = (text: string) => createRawSnippet(() => ({ render: () => `<span>${text}</span>` }));

async function contrastViolations(context: Element) {
  const result = await axe.run(context, { runOnly: { type: "rule", values: ["color-contrast"] } });
  return result.violations.flatMap((violation) => violation.nodes.map((node) => node.html));
}

/** The focus ring's colour: of the box shadows Tailwind stacks, the one with a spread. */
function ringColor(element: Element): string {
  const ring = getComputedStyle(element)
    .boxShadow.split(/,(?![^(]*\))/)
    .map((shadow) => shadow.trim())
    .find((shadow) => !shadow.endsWith(" 0px"));
  expect(ring, "no focus ring").toBeDefined();
  return ring!.replace(/(\s+-?[\d.]+px){4}$/, "");
}

beforeEach(() => {
  // The app shell paints the page; without it dark text is measured on white.
  document.body.classList.add("bg-primary");
});

afterEach(() => {
  delete document.documentElement.dataset.theme;
  document.body.classList.remove("bg-primary");
});

describe("Badge", () => {
  it("renders the content passed via the children snippet", async () => {
    render(Badge, { children: label("Active") });

    await expect.element(page.getByText("Active")).toBeVisible();
  });

  it("applies variant-specific styling", async () => {
    render(Badge, { variant: "destructive", children: label("Failed") });

    const root = page.getByText("Failed").element().closest('[data-slot="badge"]');
    expect(root?.className).toContain("text-negative-stronger");
  });

  it.each(["light", "dark"] as const)(
    "keeps a destructive badge readable at rest and when a linked one is hovered (%s)",
    async (scheme) => {
      document.documentElement.dataset.theme = scheme;
      // Small, medium-weight text like the widget status badges: 4.5:1 applies.
      render(Badge, { variant: "destructive", children: label("Pausad") });
      render(Badge, { variant: "destructive", href: "#paused", children: label("Pausad länk") });

      await userEvent.unhover(document.body);
      expect(await contrastViolations(document.body)).toEqual([]);

      await userEvent.hover(page.getByRole("link", { name: "Pausad länk" }));
      await expect.poll(() => document.getAnimations()).toHaveLength(0);
      expect(await contrastViolations(document.body)).toEqual([]);
    }
  );

  it.each(["light", "dark"] as const)(
    "shows keyboard focus on a linked destructive badge at 3:1 against the page (%s)",
    async (scheme) => {
      document.documentElement.dataset.theme = scheme;
      render(Badge, { variant: "destructive", href: "#paused", children: label("Pausad") });
      const link = page.getByRole("link", { name: "Pausad" }).element();

      await userEvent.tab();
      expect(document.activeElement).toBe(link);
      await expect.poll(() => document.getAnimations()).toHaveLength(0);
      expect(contrastAgainst(ringColor(link), document.body)).toBeGreaterThanOrEqual(3);
    }
  );
});
