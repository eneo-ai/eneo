import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import path from "node:path";
import tailwind from "@tailwindcss/postcss";
import postcss, { type AtRule, type Rule } from "postcss";
import { beforeAll, describe, expect, it } from "vitest";

// Compiles globals.css through the same PostCSS + Tailwind pipeline Vite uses,
// so regressions in @source paths, the layer order or the theme wiring fail
// here instead of silently in the browser.
const appDir = path.resolve(import.meta.dirname, "../..");
const entry = path.join(appDir, "src/styles/globals.css");

// @tailwindcss/postcss caches its compiler per input path, so every compile
// below uses its own `from` (same directory, so relative paths resolve alike).
async function compile(css: string, fileName: string): Promise<string> {
  const from = path.join(path.dirname(entry), fileName);
  const result = await postcss([tailwind({ base: appDir, optimize: false })]).process(css, {
    from
  });
  return result.css;
}

// Built at runtime so this file does not itself become a Tailwind source for
// these classes (Tailwind scans src/, tests included).
const cls = (...parts: string[]) => parts.join("-");

/** The `phone` variant's media list as compiled: below 768 px, or a phone turned sideways. */
const PHONE_MEDIA =
  "(width < 48rem), (pointer: coarse) and (height < 31.25rem) and (width < 64rem)";

let source = "";
let css = "";

beforeAll(async () => {
  source = await readFile(entry, "utf8");
  css = await compile(source, "globals.css");
}, 30_000);

describe("globals.css", () => {
  // selector → declarations of every rule in a layer, optionally only those under one @media.
  const declarationsOf = (layerName: string, inMedia?: string) => {
    const found = new Map<string, Record<string, string>>();
    postcss.parse(css).walkAtRules("layer", (layer: AtRule) => {
      if (layer.params !== layerName) return;
      layer.walkRules((rule: Rule) => {
        const media = rule.parent?.type === "atrule" ? (rule.parent as AtRule) : undefined;
        if ((media?.name === "media" ? media.params : undefined) !== inMedia) return;
        const selector = rule.selector.replace(/\s+/g, " ");
        const declarations = found.get(selector) ?? {};
        rule.walkDecls((decl) => {
          declarations[decl.prop] = decl.value;
        });
        found.set(selector, declarations);
      });
    });
    return found;
  };

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

  it("stops every transition with reduced motion, a dialog's backdrop included", () => {
    // ::backdrop is not matched by * or ::before/::after; Astryx fades the
    // drawer's and the dialogs' backdrop on their own duration.
    const rules = declarationsOf("base", "(prefers-reduced-motion: reduce)");
    const selector = [...rules.keys()].find((key) => key.split(", ").includes("*"));
    expect(selector?.split(", ")).toEqual(["*", "::before", "::after", "::backdrop"]);
    expect(rules.get(selector!)).toMatchObject({
      "animation-duration": "0.01ms",
      "transition-duration": "0.01ms"
    });
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
      "selector-option-row",
      // Every menu row: Astryx sizes it by text and padding, about 33 px.
      "dropdown-menu-item",
      // A Collapsible's trigger: its label and chevron, about 17 px.
      "collapsible-trigger"
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

  it("keeps text fields at 16 px on touch (no iOS zoom on focus) and controls from double-tap zoom", () => {
    // Text fields, not checkboxes, radios or buttons; select and textarea too.
    const fields = [...declarationsOf("components", "(pointer: coarse)").entries()].filter(
      ([, declarations]) => declarations["font-size"] === "max(1rem, 16px)"
    );
    expect(fields).toHaveLength(1);
    const selector = fields[0]![0];
    expect(selector).toMatch(/^input:not\(/);
    for (const kind of ["checkbox", "radio", "range", "file", "hidden", "button", "submit"]) {
      expect(selector).toContain(`[type="${kind}"]`);
    }
    expect(selector).toMatch(/, select, textarea$/);

    // Below Astryx (astryx-base), so a control with its own touch-action keeps it.
    const defaults = [...declarationsOf("base").entries()].filter(
      ([, declarations]) => declarations["touch-action"] === "manipulation"
    );
    expect(defaults).toHaveLength(1);
    for (const control of ["a", "button", "input", "textarea", '[role="tab"]']) {
      expect(defaults[0]![0].split(", ")).toContain(control);
    }
  });

  it("shows a tap like a hover, and gives a short viewport its own variant and bar rule", () => {
    // Tailwind's hover: is gated to hover-capable pointers; on touch it is :active.
    const media = (query: string) => {
      const found: string[] = [];
      postcss.parse(css).walkAtRules("media", (rule: AtRule) => {
        if (rule.params !== query) return;
        rule.walkRules((r: Rule) => void found.push(r.selector));
      });
      return found;
    };
    expect(media("(hover: hover)")).toContain(".hover\\:bg-ax-hover-overlay:hover");
    expect(media("(hover: none)")).toContain(".hover\\:bg-ax-hover-overlay:active");

    // `short:` is a viewport under 30rem tall.
    expect(css).toMatch(/@media \(height < 30rem\)/);
    // With a field focused on a viewport under 18.75rem, the page's bars give way.
    const bars = [...declarationsOf("components", "(height < 18.75rem)").entries()];
    expect(bars).toHaveLength(1);
    expect(bars[0]![0]).toContain("textarea:focus");
    for (const bar of ["[data-page-bar]", "[data-phone-page-bar]", "[data-own-mobile-header]"]) {
      expect(bars[0]![0]).toContain(bar);
    }
    expect(bars[0]![1]).toEqual({ display: "none" });
  });

  it("compiles `phone:` and `wide:` to a phone's layout and exactly the rest", () => {
    const WIDE_MEDIA =
      "(width >= 64rem), (width >= 48rem) and (height >= 31.25rem), (width >= 48rem) and (pointer: fine), (width >= 48rem) and (pointer: none)";
    const under = (selector: string) => {
      const found: string[] = [];
      postcss.parse(css).walkRules(selector, (rule: Rule) => {
        const parent = rule.parent as AtRule;
        found.push(parent.name === "media" ? parent.params.replace(/\s+/g, " ") : "");
      });
      return found;
    };
    // The shell's side navigation shows on `wide:`, a pushed screen's phone bar hides there.
    expect(under(".wide\\:flex")).toEqual([WIDE_MEDIA]);
    expect(under(".wide\\:hidden")).toEqual([WIDE_MEDIA]);
    expect(under(".phone\\:hidden")).toEqual([PHONE_MEDIA]);
  });

  it("hides the space's page bar on a phone while a settings section has its own", () => {
    // The `phone` variant: below 768 px, or a phone turned sideways.
    const rules = [...declarationsOf("components", PHONE_MEDIA).entries()].filter(([selector]) =>
      selector.includes('[data-editor-view="section"]')
    );
    expect(rules).toHaveLength(1);
    const [selector, declarations] = rules[0]!;
    // Only the bar outside the settings view (a section's own bar is inside it), and the
    // connection banner right under it: two offline banners do not stack either.
    expect(selector).toContain(
      'main:has([data-editor-view="section"]) [data-phone-page-bar]:not([data-editor-view] *)'
    );
    expect(selector).toContain("+ [data-connection-banner]");
    // The tab strip of a space from the menu, which has no page bar to give way.
    expect(selector).toContain('main:has([data-editor-view="section"]) [data-space-tabs]');
    expect(declarations).toEqual({ display: "none" });
  });

  it("hangs a dialog with a text field from the top on touch, under a dvh cap", () => {
    const rules = [...declarationsOf("components", "(pointer: coarse)").entries()].filter(
      ([selector]) => selector.startsWith(".astryx-dialog:has(")
    );
    expect(rules).toHaveLength(1);
    const [selector, declarations] = rules[0]!;
    for (const field of [
      "input:not(",
      "textarea",
      '[contenteditable="true"]',
      '[role="combobox"]'
    ]) {
      expect(selector).toContain(field);
    }
    // Not for a checkbox, radio, file or range input, which open no keyboard.
    for (const kind of ["checkbox", "radio", "file", "range", "button"]) {
      expect(selector).toContain(`[type="${kind}"]`);
    }
    expect(declarations).toMatchObject({
      "margin-block": "max(1rem, env(safe-area-inset-top, 0px)) auto",
      "max-height": "calc(100dvh - max(1rem, env(safe-area-inset-top, 0px)) - 1rem)"
    });
  });

  it("pads a page outside the shell by 1rem (or --page-pad) and the hardware's insets, whichever is larger", () => {
    const padSafe = declarationsOf("utilities").get(".p-safe");
    expect(padSafe).toEqual({
      "padding-top": "max(var(--page-pad, 1rem), env(safe-area-inset-top, 0px))",
      "padding-right": "max(var(--page-pad, 1rem), env(safe-area-inset-right, 0px))",
      "padding-bottom": "max(var(--page-pad, 1rem), env(safe-area-inset-bottom, 0px))",
      "padding-left": "max(var(--page-pad, 1rem), env(safe-area-inset-left, 0px))"
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
    // A filled button, and a ghost one raised into a plate (the rail's "Ny
    // konversation"), keep a native button's border when the fill turns Canvas.
    expect(
      forced.get(
        ':is(button, a)[data-variant][data-size]:not([data-variant="ghost"], [data-variant="link"]), :is(button, a)[data-variant="ghost"][data-elevation]:not([data-elevation="none"])'
      )
    ).toEqual({ border: "1px solid ButtonText" });
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

  it("makes the DateRangeInput's period button as tall as its 44 px frame on touch", () => {
    const period =
      ".astryx-date-range-input > button:not(:has(> .astryx-date-range-input-toggle-icon))";
    const rules = new Map<string, Record<string, string>>();
    postcss.parse(css).walkRules((rule: Rule) => {
      if (!rule.selector.startsWith(period)) return;
      const parent = rule.parent as AtRule | undefined;
      const media = parent?.type === "atrule" && parent.name === "media" ? parent.params : "";
      const declarations: Record<string, string> = {};
      rule.walkDecls((decl) => {
        declarations[decl.prop] = decl.value;
      });
      rules.set(`${media} ${rule.selector.slice(period.length)}`.trim(), declarations);
    });
    expect(rules.get("(pointer: coarse)")).toMatchObject({ position: "relative" });
    // 21 px of text plus 12 px above and below: a 45 px target across the button's width.
    expect(rules.get("(pointer: coarse) ::after")).toMatchObject({ inset: "-12px 0" });
  });

  it("self-hosts every required font subset as a Vite asset", () => {
    // family → subsets, from the file names (<family>-<subset>-wght-normal.woff2)
    const subsets = new Map<string, string[]>();
    postcss.parse(css).walkAtRules("font-face", (face: AtRule) => {
      const declarations: Record<string, string> = {};
      face.walkDecls((decl) => {
        declarations[decl.prop] = decl.value;
      });
      const file = declarations.src?.match(/url\("\.\.\/assets\/fonts\/([^"]+)"\)/)?.[1];
      if (!file) return;
      expect(declarations["font-display"], file).toBe("swap");
      expect(declarations["unicode-range"], file).toMatch(/^U\+/);
      expect(existsSync(path.join(appDir, "src/assets/fonts", file)), file).toBe(true);
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

  it("names the fonts on :root with their metric-matched fallbacks", () => {
    // The fallback faces size a local font to the web font's metrics, so the
    // swap to the web font does not move text.
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

  it("lets a compensated list row's content start on the page's text line", () => {
    // Astryx cancels a row's own inset (edge="outset") only as far
    // as --container-padding-inline-* allows; the list publishes the 16 px gutter.
    const gutter: Record<string, string> = {};
    postcss.parse(css).walkRules(".astryx-list", (rule: Rule) => {
      rule.walkDecls(/^--container-padding-inline-/, (decl) => {
        gutter[decl.prop] = decl.value;
      });
    });
    expect(gutter).toEqual({
      "--container-padding-inline-start": "1rem",
      "--container-padding-inline-end": "1rem"
    });
  });

  it("keeps a phone's toasts above its docked action bar", () => {
    let offsets: Record<string, string> = {};
    let media: string | undefined;
    postcss.parse(css).walkRules((rule: Rule) => {
      if (!rule.selector.includes("[data-docked-actions]") || !rule.selector.includes("toaster")) {
        return;
      }
      media = (rule.parent as AtRule).params;
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
    // Where the bar docks: a phone, held either way.
    expect(media).toBe(PHONE_MEDIA);
  });

  it("wraps a menu row's label instead of cutting it off", () => {
    // Astryx ends a string label in an ellipsis: on a narrow screen or at 200%
    // text, "Kopiera som formaterad text" lost its end with no way to read it.
    const components = declarationsOf("components");
    expect(components.get(".astryx-dropdown-menu .astryx-item span")).toMatchObject({
      "white-space": "normal",
      "overflow-wrap": "anywhere"
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
