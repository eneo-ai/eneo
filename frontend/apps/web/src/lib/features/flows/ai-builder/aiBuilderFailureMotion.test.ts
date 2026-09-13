import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

// The failure card's one authored moment runs on the shared motion tokens:
// no literal duration or easing in the component, and the installed
// transitions-dev panel reveal maps onto the scale in the global stylesheet.
const here = import.meta.dirname;
const component = readFileSync(resolve(here, "BuilderReviewScreen.svelte"), "utf8");
const appCss = readFileSync(resolve(here, "../../../../app.css"), "utf8");

describe("failure card motion", () => {
  it("declares every transition of the card through tokens", () => {
    const style = component.slice(component.indexOf("<style"));
    const declarations = [...style.matchAll(/transition:\s*([^;]+);/g)].map((match) => match[1]);
    expect(declarations.length).toBeGreaterThanOrEqual(1);
    for (const declaration of declarations) {
      if (declaration.trim().startsWith("none")) continue;
      expect(declaration).not.toMatch(/\d+m?s\b/);
      expect(declaration).toMatch(/var\(--panel-open-dur\)/);
      expect(declaration).toMatch(/var\(--panel-ease\)/);
    }
    expect(style).toContain("@media (prefers-reduced-motion: reduce)");
    expect(component).not.toMatch(/transition:(fade|fly|slide|scale)/);
    // One moment: the panel reveal, nothing layered on the words.
    expect(component).not.toContain("t-text-swap");
  });

  it("maps the panel reveal onto the shared scale", () => {
    expect(appCss).toMatch(/--panel-open-dur:\s*var\(--duration-slow\)/);
    // Entrance only: no exit token, no exit machinery.
    expect(appCss).not.toContain("--panel-close-dur");
    expect(component).not.toContain("panel-close-dur");
    expect(appCss).toMatch(/--panel-ease:\s*var\(--ease-smooth-out\)/);
    expect(appCss).toMatch(/--panel-blur:\s*var\(--blur-small\)/);
    expect(appCss).toMatch(/--duration-slow:\s*400ms/);
    expect(appCss).not.toContain("--text-swap-");
  });
});
