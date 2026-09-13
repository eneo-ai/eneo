import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

// The failure card's one authored moment runs on the shared motion tokens:
// no literal duration or easing in the component, and the two installed
// transitions-dev snippets map onto the scale in the global stylesheet.
const here = import.meta.dirname;
const component = readFileSync(resolve(here, "BuilderReviewScreen.svelte"), "utf8");
const appCss = readFileSync(resolve(here, "../../../../app.css"), "utf8");

describe("failure card motion", () => {
  it("declares every transition of the card through tokens", () => {
    const style = component.slice(component.indexOf("<style"));
    const declarations = [...style.matchAll(/transition:\s*([^;]+);/g)].map((match) => match[1]);
    expect(declarations.length).toBeGreaterThanOrEqual(4);
    for (const declaration of declarations) {
      if (declaration.trim().startsWith("none")) continue;
      expect(declaration).not.toMatch(/\d+m?s\b/);
      expect(declaration).toMatch(/var\(--(panel|text-swap)-(open-dur|close-dur|dur)\)/);
      expect(declaration).toMatch(/var\(--(panel|text-swap)-ease\)/);
    }
    expect(style).toContain("@media (prefers-reduced-motion: reduce)");
    expect(component).not.toMatch(/transition:(fade|fly|slide|scale)/);
  });

  it("maps the panel reveal and text swap onto the shared scale", () => {
    expect(appCss).toMatch(/--panel-open-dur:\s*var\(--duration-slow\)/);
    expect(appCss).toMatch(/--panel-close-dur:\s*var\(--duration-medium\)/);
    expect(appCss).toMatch(/--panel-ease:\s*var\(--ease-smooth-out\)/);
    expect(appCss).toMatch(/--text-swap-dur:\s*var\(--duration-quick\)/);
    expect(appCss).toMatch(/--text-swap-ease:\s*var\(--ease-in-out\)/);
    expect(appCss).toMatch(/--text-swap-translate-y:\s*var\(--distance-micro\)/);
    expect(appCss).toMatch(/--text-swap-blur:\s*var\(--blur-small\)/);
    expect(appCss).toMatch(/--duration-medium:\s*350ms/);
  });
});
