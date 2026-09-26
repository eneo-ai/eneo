import { readFile } from "node:fs/promises";
import path from "node:path";
import tailwind from "@tailwindcss/postcss";
import postcss, { type AtRule, type Rule } from "postcss";
import { beforeAll, describe, expect, it } from "vitest";

// Compiles globals.css through the same PostCSS + Tailwind pipeline Next uses,
// so regressions in @source paths, the layer order or the theme wiring fail
// here instead of silently in the browser.
const appDir = path.resolve(import.meta.dirname, "../..");
const entry = path.join(appDir, "src/app/globals.css");

// @tailwindcss/postcss caches its compiler per input path, so every compile
// below uses its own `from` (same directory, so relative paths resolve alike).
async function compile(css: string, fileName: string): Promise<string> {
  const from = path.join(appDir, "src/app", fileName);
  const result = await postcss([tailwind({ base: appDir, optimize: false })]).process(css, {
    from
  });
  return result.css;
}

// Built at runtime so this file does not itself become a Tailwind source for
// these classes (Tailwind scans src/, tests included).
const cls = (...parts: string[]) => parts.join("-");

let source = "";
let css = "";

beforeAll(async () => {
  source = await readFile(entry, "utf8");
  css = await compile(source, "globals.css");
}, 30_000);

describe("globals.css", () => {
  it("scans Streamdown's build so its markdown classes are emitted", async () => {
    // Only the @source lines, with automatic detection off: app code cannot
    // mask a broken path. Without them numbered lists in chat answers render
    // without numbers.
    const sources = source.split("\n").filter((line) => line.startsWith("@source "));
    expect(sources.length).toBeGreaterThan(0);
    const scanned = await compile(
      ['@import "tailwindcss/utilities.css" source(none);', ...sources].join("\n"),
      "__streamdown-sources.css"
    );
    expect(scanned).toContain(`.${cls("list", "decimal")}`);
    expect(scanned).toContain(`.${cls("list", "inside")}`);
  });

  it("declares the cascade layer order before any layered rules", () => {
    const order =
      "@layer properties, reset, theme, base, astryx-base, astryx-theme, components, utilities;";
    const declared = css.indexOf(order);
    expect(declared).toBeGreaterThanOrEqual(0);
    expect(css.search(/@layer [\w-]+\s*\{/)).toBeGreaterThan(declared);
  });

  it("includes Astryx component styles and the built Eneo theme", () => {
    expect(css).toContain('@scope ([data-astryx-theme="eneo"])');
    expect(css).toMatch(/--color-accent:\s*light-dark\(#1A6FD2, #4D94F2\)/);
    // Neutral's own stylesheet must not be imported next to the Eneo build.
    expect(css).not.toContain('[data-astryx-theme="neutral"]');
  });

  it("maps the shadcn variables onto Astryx tokens instead of raw colours", () => {
    const contract = css.match(/:root,\s*\[data-astryx-theme\]\s*\{([^}]*)\}/)?.[1] ?? "";
    expect(contract).toContain("--primary: var(--color-accent)");
    expect(contract).toContain("--background: var(--color-background-surface)");
    expect(contract).not.toMatch(/#[0-9a-f]{3,8}\b|oklch\(|rgba?\(/i);
  });

  it("pins color-scheme to the next-themes class", () => {
    expect(css).toMatch(/:root\.dark,\s*:root\.dark \[data-astryx-theme\]:not\(\[data-theme\]\)/);
  });

  it("paints the hover tint over filled legacy controls instead of fading the fill", () => {
    // Used by the shadcn Button and Badge fills; the contrast of their labels
    // on this overlay is checked in eneo-theme.contrast.test.ts.
    const rule = css.match(/\.hover\\:bg-ax-hover-overlay\s*\{([\s\S]*?)\n {2}\}/)?.[1] ?? "";
    expect(rule).toContain(
      "background-image: linear-gradient(var(--color-overlay-hover), var(--color-overlay-hover))"
    );
  });

  it("gives Astryx controls 44 px targets on a coarse pointer", () => {
    // selector → declarations of every rule under @media (pointer: coarse)
    const coarse = new Map<string, Record<string, string>>();
    postcss.parse(css).walkAtRules("media", (media: AtRule) => {
      if (media.params !== "(pointer: coarse)") return;
      media.walkRules((rule: Rule) => {
        const declarations = coarse.get(rule.selector) ?? {};
        rule.walkDecls((decl) => {
          declarations[decl.prop] = decl.value;
        });
        coarse.set(rule.selector, declarations);
      });
    });

    // Element sizes: buttons (icon-only ones are square), menu triggers,
    // tabs, nav items, inputs and selectors.
    expect(coarse.get(":scope")).toMatchObject({
      "--size-element-sm": "44px",
      "--size-element-md": "44px",
      "--size-element-lg": "44px"
    });
    for (const component of [
      "segmented-control-item",
      "checkbox-input",
      "radio-list-item",
      "switch-field"
    ]) {
      expect(coarse.get(`.astryx-${component}`)).toMatchObject({ "min-height": "44px" });
    }
    // The native inputs checkbox, radio and switch take pointer input on.
    const inputs = [...coarse.entries()].find(([selector]) =>
      selector.includes(".astryx-checkbox-input, .astryx-radio-list-item, .astryx-switch-field")
    );
    expect(inputs?.[1]).toMatchObject({ "min-inline-size": "44px", "min-block-size": "44px" });
  });

  it("makes the toast close button a 24 px target (44 px on touch) with a full-strength focus outline", () => {
    const button = '[data-sonner-toast][data-styled="true"] [data-close-button]';
    const rules = new Map<string, Record<string, string>>();
    postcss.parse(css).walkRules((rule: Rule) => {
      if (!rule.selector.includes(button)) return;
      const declarations: Record<string, string> = {};
      rule.walkDecls((decl) => {
        declarations[decl.prop] = decl.value;
      });
      rules.set(rule.selector.replace(/^.*\[data-close-button\]/, ""), declarations);
    });
    expect(rules.get("")).toMatchObject({ width: "24px", height: "24px" });
    expect(rules.get(":focus-visible")).toMatchObject({ outline: "2px solid var(--ring)" });
    expect(rules.get("::after")).toMatchObject({ inset: "-10px" });
  });
});
