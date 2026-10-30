import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import path from "node:path";
import tailwind from "@tailwindcss/postcss";
import postcss, { type AtRule, type Rule } from "postcss";
import { beforeAll, describe, expect, it } from "vitest";

// Compiles globals.css through the same PostCSS + Tailwind pipeline Next uses,
// so regressions in @source paths, the layer order or the theme wiring fail
// here instead of silently in the browser.
const appDir = path.resolve(import.meta.dirname, "../..");
const entry = path.join(appDir, "src/styles/globals.css");

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

  it("moves the shadcn layer on Astryx's motion scale, not Tailwind's defaults", () => {
    // Astryx components animate with --duration-fast and --ease-standard; the
    // transition-* and ease-out utilities of the legacy layer must match them.
    const declarations = new Map<string, string>();
    postcss.parse(css).walkRules(".transition-colors", (rule: Rule) => {
      rule.walkDecls((decl) => {
        declarations.set(decl.prop, decl.value);
      });
    });
    expect(declarations.get("transition-duration")).toBe(
      "var(--tw-duration, var(--duration-fast))"
    );
    expect(declarations.get("transition-timing-function")).toBe(
      "var(--tw-ease, var(--ease-standard))"
    );
  });

  it("pins color-scheme to the next-themes class", () => {
    expect(css).toMatch(/:root\.dark,\s*:root\.dark \[data-astryx-theme\]:not\(\[data-theme\]\)/);
  });

  it("paints the hover tint over filled legacy controls instead of fading the fill", () => {
    // Used by the shadcn Button and Badge fills; the contrast of their labels
    // on this overlay is checked in eneo-theme.contrast.test.ts.
    let backgroundImage: string | undefined;
    postcss.parse(css).walkRules(".hover\\:bg-ax-hover-overlay:hover", (rule: Rule) => {
      rule.walkDecls("background-image", (decl) => {
        backgroundImage = decl.value;
      });
    });
    expect(backgroundImage).toBe(
      "linear-gradient(var(--color-overlay-hover), var(--color-overlay-hover))"
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
      "--size-element-lg": "44px",
      // The touch type scale: body and labels 15 px, supporting text 13 px.
      "--text-body-size": "0.9375rem",
      "--text-label-size": "0.9375rem",
      "--text-supporting-size": "0.8125rem"
    });
    // Hand-built text follows it: Tailwind's text-sm and text-xs.
    expect(coarse.get(":root")).toMatchObject({
      "--text-sm": "0.9375rem",
      "--text-xs": "0.8125rem"
    });
    for (const component of [
      "segmented-control-item",
      "checkbox-input",
      "radio-list-item",
      "switch-field",
      "selector-search",
      "selector-option-row"
    ]) {
      expect(coarse.get(`.astryx-${component}`)).toMatchObject({ "min-height": "44px" });
    }
    // The native inputs checkbox, radio and switch take pointer input on.
    const inputs = [...coarse.entries()].find(([selector]) =>
      selector.includes(".astryx-checkbox-input, .astryx-radio-list-item, .astryx-switch-field")
    );
    expect(inputs?.[1]).toMatchObject({ "min-inline-size": "44px", "min-block-size": "44px" });
  });

  it("keeps phones and tablets steady: no pull-to-refresh, no blur, the theme's drawer timing, safe areas", () => {
    // selector → declarations of every rule in @layer components (it beats
    // Astryx's own styles in astryx-base whatever their specificity).
    const components = new Map<string, Record<string, string>>();
    postcss.parse(css).walkAtRules("layer", (layer: AtRule) => {
      if (layer.params !== "components") return;
      layer.walkRules((rule: Rule) => {
        const selector = rule.selector.replace(/\s+/g, " ");
        const declarations = components.get(selector) ?? {};
        rule.walkDecls((decl) => {
          declarations[decl.prop] = decl.value;
        });
        components.set(selector, declarations);
      });
    });

    // Pulling down never reloads the page (and drops a draft or a streaming
    // answer); main#main-content, the one scroller, keeps its bounce to itself.
    expect(components.get("html, body")).toMatchObject({ "overscroll-behavior": "none" });
    expect(components.get("#main-content")).toMatchObject({ "overscroll-behavior-y": "contain" });
    // The scrim alone separates the drawer and dialogs from the page.
    expect(components.get(".astryx-mobile-nav::backdrop, .astryx-dialog::backdrop")).toMatchObject({
      "backdrop-filter": "none"
    });
    // The drawer moves at the theme's open duration (225 ms), not 300 ms.
    expect(components.get(".astryx-mobile-nav")).toMatchObject({
      "--duration-medium": "var(--duration-medium-min)"
    });
    // Its panel keeps its content clear of the notch and the home indicator.
    expect(components.get(".astryx-mobile-nav > div:first-child")).toMatchObject({
      "padding-top": "env(safe-area-inset-top, 0px)",
      "padding-bottom": "env(safe-area-inset-bottom, 0px)",
      "padding-inline-start": "env(safe-area-inset-left, 0px)"
    });
    // A PageBar's title is hidden until the page scrolls it in.
    expect(components.get(".page-bar-title")).toMatchObject({
      opacity: "0",
      "animation-timeline": "scroll(nearest block)"
    });
  });

  it("marks what is selected, current or highlighted with Highlight in forced colours", () => {
    // selector → declarations of every rule under an unlayered
    // @media (forced-colors: active): a layered rule would lose to Tailwind.
    const forced = new Map<string, Record<string, string>>();
    postcss.parse(css).walkAtRules("media", (media: AtRule) => {
      if (media.params !== "(forced-colors: active)" || media.parent?.type !== "root") return;
      media.walkRules((rule: Rule) => {
        const declarations = forced.get(rule.selector) ?? {};
        rule.walkDecls((decl) => {
          declarations[decl.prop] = decl.value;
        });
        forced.set(rule.selector.replace(/\s+/g, " "), declarations);
      });
    });

    // The current nav item's label: no Canvas backplate over HighlightText.
    expect(
      forced.get('.astryx-side-nav-item[data-selected="selected"] > span:not(:has(*))')
    ).toEqual({ "forced-color-adjust": "none" });
    // A selected tab's bar.
    expect(forced.get('.astryx-tab-indicator[data-selected="selected"]')).toEqual({
      "background-color": "Highlight"
    });
    // The focused menu item and the palette's active option.
    expect(
      forced.get(
        '.astryx-dropdown-menu-item:focus, .astryx-command-palette-item[aria-selected="true"]'
      )
    ).toMatchObject({ outline: "2px solid Highlight" });
    // The current page and the legacy active tab.
    expect(
      forced.get(
        '.astryx-pagination [aria-current="page"], [data-slot="tabs-trigger"][data-state="active"]'
      )
    ).toEqual({
      "forced-color-adjust": "none",
      "background-color": "Highlight",
      color: "HighlightText"
    });
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

  it("makes the DateInput's calendar toggle a 24 px target (44 px on touch) in place", () => {
    const toggle = ".astryx-date-input > button:has(> .astryx-date-input-toggle-icon)";
    // "<media> <pseudo-element>" → declarations
    const rules = new Map<string, Record<string, string>>();
    postcss.parse(css).walkRules((rule: Rule) => {
      if (!rule.selector.startsWith(toggle)) return;
      const parent = rule.parent as AtRule | undefined;
      const media = parent?.type === "atrule" && parent.name === "media" ? parent.params : "";
      const declarations: Record<string, string> = {};
      rule.walkDecls((decl) => {
        declarations[decl.prop] = decl.value;
      });
      rules.set(`${media} ${rule.selector.slice(toggle.length)}`.trim(), declarations);
    });
    // The negative margin gives the growth back: the field's text stays put.
    expect(rules.get("")).toMatchObject({
      "min-inline-size": "24px",
      "min-block-size": "24px",
      margin: "-4px"
    });
    expect(rules.get("(pointer: coarse)")).toMatchObject({ position: "relative" });
    expect(rules.get("(pointer: coarse) ::after")).toMatchObject({ inset: "-10px" });
  });

  it("self-hosts every subset Next's font loader served, from public/fonts", () => {
    // family → subsets, from the file names (<family>-<subset>-wght-normal.woff2)
    const subsets = new Map<string, string[]>();
    postcss.parse(css).walkAtRules("font-face", (face: AtRule) => {
      const declarations: Record<string, string> = {};
      face.walkDecls((decl) => {
        declarations[decl.prop] = decl.value;
      });
      const file = declarations.src?.match(/url\("\/fonts\/([^"]+)"\)/)?.[1];
      if (!file) return;
      expect(declarations["font-display"], file).toBe("swap");
      expect(declarations["unicode-range"], file).toMatch(/^U\+/);
      expect(existsSync(path.join(appDir, "public/fonts", file)), file).toBe(true);
      const family = declarations["font-family"] ?? "";
      const subset = file.match(
        /^[a-z0-9-]+?-((?:latin|cyrillic|greek|vietnamese)(?:-ext)?)-wght/
      )?.[1];
      subsets.set(family, [...(subsets.get(family) ?? []), subset ?? file]);
    });
    const all = ["cyrillic-ext", "cyrillic", "greek", "vietnamese", "latin-ext", "latin"];
    expect(Object.fromEntries(subsets)).toEqual({
      '"Figtree"': ["latin-ext", "latin"],
      '"JetBrains Mono"': all,
      '"Source Serif 4"': all
    });
  });

  it("names the fonts on :root with the metric-matched fallbacks Next generated", () => {
    // The fallback faces size a local font to the web font's metrics, so the
    // swap to the web font does not move text (the values Next's font loader generated).
    const fallbacks = new Map<string, Record<string, string>>();
    postcss.parse(css).walkAtRules("font-face", (face: AtRule) => {
      const declarations: Record<string, string> = {};
      face.walkDecls((decl) => {
        declarations[decl.prop] = decl.value;
      });
      if (declarations.src?.startsWith("local(")) {
        fallbacks.set(declarations["font-family"] ?? "", declarations);
      }
    });
    expect(Object.fromEntries(fallbacks)).toEqual({
      '"Figtree Fallback"': {
        "font-family": '"Figtree Fallback"',
        src: 'local("Arial")',
        "ascent-override": "94.32%",
        "descent-override": "24.82%",
        "line-gap-override": "0%",
        "size-adjust": "100.72%"
      },
      '"JetBrains Mono Fallback"': {
        "font-family": '"JetBrains Mono Fallback"',
        src: 'local("Arial")',
        "ascent-override": "75.79%",
        "descent-override": "22.29%",
        "line-gap-override": "0%",
        "size-adjust": "134.59%"
      },
      '"Source Serif 4 Fallback"': {
        "font-family": '"Source Serif 4 Fallback"',
        src: 'local("Times New Roman")',
        "ascent-override": "87.87%",
        "descent-override": "28.41%",
        "line-gap-override": "0%",
        "size-adjust": "117.91%"
      }
    });

    const root: Record<string, string> = {};
    postcss.parse(css).walkRules(":root", (rule: Rule) => {
      rule.walkDecls(/^--font-(figtree|jetbrains-mono|source-serif)$/, (decl) => {
        root[decl.prop] = decl.value;
      });
    });
    expect(root).toEqual({
      "--font-figtree": '"Figtree", "Figtree Fallback"',
      "--font-jetbrains-mono": '"JetBrains Mono", "JetBrains Mono Fallback"',
      "--font-source-serif": '"Source Serif 4", "Source Serif 4 Fallback", serif'
    });
  });

  it("makes an Astryx list row with a link one target, its own controls above the link", () => {
    const rules = new Map<string, Record<string, string>>();
    postcss.parse(css).walkRules((rule: Rule) => {
      if (!rule.selector.includes(".astryx-item")) return;
      const decls: Record<string, string> = {};
      rule.walkDecls((decl) => {
        decls[decl.prop] = decl.value;
      });
      rules.set(rule.selector, decls);
    });
    expect(rules.get(".astryx-item > a::after")).toMatchObject({
      content: '""',
      position: "absolute",
      inset: "0"
    });
    const controls = [...rules].find(([selector]) => selector.includes(":has(> a)"));
    expect(controls?.[1]).toMatchObject({ position: "relative", "z-index": "1" });
  });

  it("keeps a phone's toasts above its docked action bar", () => {
    let offsets: Record<string, string> = {};
    postcss.parse(css).walkRules((rule: Rule) => {
      if (!rule.selector.includes("[data-docked-actions]") || !rule.selector.includes("toaster")) {
        return;
      }
      rule.walkDecls((decl) => {
        offsets = {
          ...offsets,
          [decl.prop]: `${decl.value}${decl.important ? " !important" : ""}`
        };
      });
    });
    // sonner sets these inline: only !important moves them.
    expect(offsets).toMatchObject({
      "--offset-bottom": expect.stringMatching(
        /^calc\(\s*var\(--docked-actions-height[\s\S]* !important$/
      ),
      "--mobile-offset-bottom": expect.stringMatching(
        /^calc\(\s*var\(--docked-actions-height[\s\S]* !important$/
      )
    });
  });

  it("keeps what an Astryx table scrolls inside its scroll box", () => {
    let position: string | undefined;
    postcss.parse(css).walkRules(".astryx-table-scroll-wrapper", (rule: Rule) => {
      rule.walkDecls("position", (decl) => {
        position = decl.value;
      });
    });
    expect(position).toBe("relative");
  });

  it("wraps a sortable header's label, and on touch makes it a 44 px target with its arrows shown", () => {
    const header = ".astryx-table-header-cell";
    // "<media> <selector>" → declarations
    const rules = new Map<string, Record<string, string>>();
    postcss.parse(css).walkRules((rule: Rule) => {
      if (!rule.selector.startsWith(header)) return;
      const parent = rule.parent as AtRule | undefined;
      const media = parent?.type === "atrule" && parent.name === "media" ? parent.params : "";
      const declarations: Record<string, string> = {};
      rule.walkDecls((decl) => {
        declarations[decl.prop] = decl.value;
      });
      rules.set(`${media} ${rule.selector}`.trim(), declarations);
    });
    // Astryx's ellipsis cannot reach a label inside the flex sort button: a
    // long one was cut off mid-word.
    expect(rules.get(`${header} button`)).toMatchObject({ "white-space": "normal" });
    expect(rules.get(`(pointer: coarse) ${header} button`)).toMatchObject({
      "min-block-size": "44px"
    });
    // The unsorted arrows Astryx shows only on hover.
    expect(
      rules.get(`(pointer: coarse) ${header} button > span:has(> .astryx-icon)`)
    ).toMatchObject({ opacity: "1" });
  });
});
