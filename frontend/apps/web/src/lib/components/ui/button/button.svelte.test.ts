import { createRawSnippet } from "svelte";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { contrastAgainst } from "$lib/features/widget/components/contrastProbe";
import { Button } from "./index.js";
import "../../../../app.css";

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

describe("Button", () => {
  it.each(["light", "dark"] as const)(
    "keeps a destructive button readable at rest and on hover (%s)",
    async (scheme) => {
      document.documentElement.dataset.theme = scheme;
      render(Button, { variant: "destructive", children: label("Ta bort") });
      const button = page.getByRole("button", { name: "Ta bort" });

      await userEvent.unhover(document.body);
      expect(await contrastViolations(document.body)).toEqual([]);

      await userEvent.hover(button);
      // The hover colours are what axe measures, not a transition halfway there.
      await expect.poll(() => document.getAnimations()).toHaveLength(0);
      expect(await contrastViolations(document.body)).toEqual([]);
    }
  );

  it.each(["light", "dark"] as const)(
    "shows keyboard focus on a destructive button at 3:1 against the page (%s)",
    async (scheme) => {
      document.documentElement.dataset.theme = scheme;
      render(Button, { variant: "destructive", children: label("Arkivera") });
      const button = page.getByRole("button", { name: "Arkivera" }).element();

      await userEvent.tab();
      expect(document.activeElement).toBe(button);
      await expect.poll(() => document.getAnimations()).toHaveLength(0);
      // WCAG 1.4.11: the ring is the only focus cue (outline-none).
      expect(contrastAgainst(ringColor(button), document.body)).toBeGreaterThanOrEqual(3);
    }
  );
});
