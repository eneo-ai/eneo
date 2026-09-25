/**
 * WCAG 2.2 AA colour contrast for the Eneo theme (ACCESSIBILITY.md → Colour
 * and contrast). Reads the built tokens (src/theme/eneo.js, what ships; `bun
 * run lint` keeps it in sync with eneo-theme.ts) and checks every documented
 * foreground/background pair in light AND dark mode:
 *
 * - 1.4.3  text 4.5:1 (all app text is treated as small text)
 * - 1.4.11 non-text 3:1: form-control boundaries, the focus ring, icons and
 *   status dots
 *
 * Translucent tokens (overlays, dark-mode muted fills) are alpha-composited
 * over the surface they sit on. Disabled text is exempt (1.4.3) and not listed.
 *
 * When you add a colour token, or start using one on a new surface, add the
 * pair here. Never lower a threshold: change the token.
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { eneoTheme } from "./eneo";

const TEXT = 4.5;
const NON_TEXT = 3;

const tokens: Record<string, string> = { ...eneoTheme.tokens, ...eneoTheme.localTokens };

// Plain surfaces, darkest to lightest in light mode.
const SURFACES = {
  body: "--color-background-body",
  surface: "--color-background-surface",
  card: "--color-background-card",
  popover: "--color-background-popover",
  muted: "--color-background-muted",
  sunken: "--eneo-color-background-sunken"
} as const;
type Surface = keyof typeof SURFACES;
const ALL_SURFACES = Object.keys(SURFACES) as Surface[];
// Where panels, dialogs, menus and list rows put interactive content.
const RAISED: Surface[] = ["surface", "card", "popover"];

// Interactive row states (bg-ax-hover, bg-ax-selected, bg-ax-pressed).
const HOVER = "--color-overlay-hover";
const SELECTED = "--color-neutral";
const PRESSED = "--color-overlay-pressed";

const MODES = [
  { name: "light", index: 0 },
  { name: "dark", index: 1 }
] as const;
type Mode = (typeof MODES)[number];

type Rgba = { r: number; g: number; b: number; a: number };

/** Splits `light-dark(a, b)` into its two values (commas inside rgba() kept). */
function modeValue(value: string, mode: Mode): string {
  const match = /^light-dark\(([\s\S]*)\)$/.exec(value.trim());
  if (!match) return value.trim();
  const parts: string[] = [];
  let depth = 0;
  let current = "";
  for (const char of match[1]!) {
    if (char === "(") depth += 1;
    if (char === ")") depth -= 1;
    if (char === "," && depth === 0) {
      parts.push(current.trim());
      current = "";
    } else {
      current += char;
    }
  }
  parts.push(current.trim());
  if (parts.length !== 2) throw new Error(`Cannot split light-dark() value: ${value}`);
  return parts[mode.index]!;
}

function parseColor(raw: string): Rgba {
  const value = raw.trim().toLowerCase();
  if (value === "white") return { r: 255, g: 255, b: 255, a: 1 };
  if (value === "black") return { r: 0, g: 0, b: 0, a: 1 };
  const hex = /^#([0-9a-f]{3,8})$/.exec(value)?.[1];
  if (hex && [3, 6, 8].includes(hex.length)) {
    const full = hex.length === 3 ? [...hex].map((c) => c + c).join("") : hex;
    const channel = (i: number) => parseInt(full.slice(i, i + 2), 16);
    return {
      r: channel(0),
      g: channel(2),
      b: channel(4),
      a: full.length === 8 ? channel(6) / 255 : 1
    };
  }
  const rgb = /^rgba?\(([^)]*)\)$/.exec(value)?.[1];
  if (rgb) {
    const [r = NaN, g = NaN, b = NaN, a = 1] = rgb
      .split(/[\s,/]+/)
      .filter(Boolean)
      .map(Number);
    if ([r, g, b, a].every(Number.isFinite)) return { r, g, b, a };
  }
  throw new Error(`Unsupported colour "${raw}": extend parseColor() in this test`);
}

function color(token: string, mode: Mode): Rgba {
  const value = tokens[token];
  if (value === undefined) throw new Error(`Unknown token ${token}`);
  const resolved = modeValue(value, mode);
  const reference = /^var\((--[\w-]+)\)$/.exec(resolved)?.[1];
  return reference ? color(reference, mode) : parseColor(resolved);
}

/** Paints `top` over an opaque `bottom`. */
function over(top: Rgba, bottom: Rgba): Rgba {
  const mix = (a: number, b: number) => a * top.a + b * (1 - top.a);
  return { r: mix(top.r, bottom.r), g: mix(top.g, bottom.g), b: mix(top.b, bottom.b), a: 1 };
}

function surface(name: Surface, mode: Mode): Rgba {
  const base = color(SURFACES.surface, mode);
  return over(color(SURFACES[name], mode), base);
}

function luminance({ r, g, b }: Rgba): number {
  const linear = (channel: number) => {
    const c = channel / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
}

function contrastRatio(foreground: Rgba, background: Rgba): number {
  const fg = luminance(foreground.a < 1 ? over(foreground, background) : foreground);
  const bg = luminance(background);
  return (Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05);
}

type Pair = { fg: string; on: string; background: (mode: Mode) => Rgba; min: number };

const onSurfaces = (fg: string[], surfaces: Surface[], min: number): Pair[] =>
  fg.flatMap((token) =>
    surfaces.map((name) => ({
      fg: token,
      on: name,
      background: (mode: Mode) => surface(name, mode),
      min
    }))
  );

const onTint = (fg: string, tint: string, surfaces: Surface[], min: number): Pair[] =>
  surfaces.map((name) => ({
    fg,
    on: `${tint} over ${name}`,
    background: (mode: Mode) => over(color(tint, mode), surface(name, mode)),
    min
  }));

const onFill = (fg: string, fill: string, min: number): Pair => ({
  fg,
  on: fill,
  background: (mode: Mode) => over(color(fill, mode), surface("surface", mode)),
  min
});

const STATUS = ["success", "warning", "error"] as const;
// Eneo categorical hues plus the Neutral cyan/gray that Badge variants use.
const HUES = ["blue", "teal", "purple", "orange", "pink", "green", "yellow", "red", "cyan", "gray"];

const GROUPS: Record<string, Pair[]> = {
  "text on every surface (1.4.3)": onSurfaces(
    [
      "--color-text-primary",
      "--color-text-secondary",
      "--eneo-color-text-tertiary",
      "--color-text-accent",
      ...STATUS.map((status) => `--color-${status}`)
    ],
    ALL_SURFACES,
    TEXT
  ),
  "text on hover, selected and pressed rows (1.4.3)": [
    ...["--color-text-primary", "--color-text-secondary"].flatMap((fg) =>
      [HOVER, SELECTED, PRESSED].flatMap((tint) => onTint(fg, tint, ["body", ...RAISED], TEXT))
    ),
    // Tertiary is for plain surfaces and hover/selected rows inside panels;
    // on body-coloured rows (the sidebar) and pressed states use secondary.
    ...[HOVER, SELECTED].flatMap((tint) => onTint("--eneo-color-text-tertiary", tint, RAISED, TEXT))
  ],
  "on-colours on their fills (1.4.3)": [
    onFill("--color-on-accent", "--color-accent", TEXT),
    ...STATUS.flatMap((status) => [
      onFill(`--color-on-${status}`, `--color-${status}`, TEXT),
      onFill(`--color-on-${status}`, `--astryx-theme-neutral-color-status-fill-${status}`, TEXT)
    ]),
    onFill("--color-on-accent", "--astryx-theme-neutral-color-status-fill-accent", TEXT)
  ],
  "status and accent text on their muted fills (1.4.3)": [
    ...STATUS.flatMap((status) =>
      onTint(`--color-${status}`, `--color-${status}-muted`, RAISED, TEXT)
    ),
    ...onTint("--color-text-accent", "--color-accent-muted", RAISED, TEXT),
    ...onTint("--color-text-primary", "--color-accent-muted", RAISED, TEXT)
  ],
  "categorical text and icons on their muted fills (1.4.3, 1.4.11)": HUES.flatMap((hue) => [
    ...onTint(`--color-text-${hue}`, `--color-background-${hue}`, RAISED, TEXT),
    ...onTint(`--color-icon-${hue}`, `--color-background-${hue}`, RAISED, NON_TEXT)
  ]),
  "form-control boundaries (1.4.11)": [
    ...onSurfaces(["--eneo-color-border-control"], ALL_SURFACES, NON_TEXT),
    ...[HOVER, SELECTED].flatMap((tint) =>
      onTint("--eneo-color-border-control", tint, RAISED, NON_TEXT)
    )
  ],
  "focus ring, checked controls and accent icons (1.4.11)": onSurfaces(
    ["--color-accent", "--color-icon-accent"],
    ALL_SURFACES,
    NON_TEXT
  ),
  "icons and status dots (1.4.11)": onSurfaces(
    [
      "--color-icon-primary",
      "--color-icon-secondary",
      ...(["accent", ...STATUS] as const).map(
        (status) => `--astryx-theme-neutral-color-status-fill-${status}`
      )
    ],
    ALL_SURFACES,
    NON_TEXT
  )
};

describe.each(MODES)("Eneo theme contrast, $name mode", (mode) => {
  it.each(Object.entries(GROUPS))("%s", (_group, pairs) => {
    const failures = pairs.flatMap(({ fg, on, background, min }) => {
      const ratio = contrastRatio(color(fg, mode), background(mode));
      return ratio >= min ? [] : [`${fg} on ${on}: ${ratio.toFixed(2)}:1 < ${min}:1`];
    });
    expect(failures).toEqual([]);
  });
});

// The pairs above only help if controls actually draw with the control token.
describe("form controls use the 3:1 control border", () => {
  const CONTROL = "var(--eneo-color-border-control)";
  const components = (eneoTheme.components ?? {}) as Record<
    string,
    { base?: Record<string, string> } | undefined
  >;

  it.each([
    "text-input",
    "text-area",
    "number-input",
    "date-input",
    "date-range-input",
    "date-time-input",
    "time-input",
    "selector",
    "multi-selector",
    "complex-selector",
    "typeahead",
    "file-input",
    "input-group",
    "checkbox-indicator",
    "radio-indicator",
    "chat-composer"
  ])("Astryx %s", (key) => {
    expect(components[key]?.base?.["--color-border-emphasized"]).toBe(CONTROL);
  });

  it("Astryx switch track", () => {
    expect(components.switch?.base?.["--color-background-gray"]).toBe(CONTROL);
  });

  it("shadcn --input (border-input, the unchecked switch track)", () => {
    const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
    expect(css).toMatch(/--input:\s*var\(--eneo-color-border-control\);/);
  });
});

describe("contrast helpers", () => {
  it("match the WCAG reference values", () => {
    const white = parseColor("#FFFFFF");
    expect(contrastRatio(parseColor("#000"), white)).toBeCloseTo(21, 5);
    expect(contrastRatio(parseColor("#767676"), white)).toBeCloseTo(4.54, 2);
    expect(contrastRatio(parseColor("#FFFFFF"), white)).toBe(1);
  });

  it("composites translucent colours over their background", () => {
    const halfBlack = parseColor("rgba(0, 0, 0, 0.5)");
    const composite = over(halfBlack, parseColor("#FFFFFF"));
    expect(composite).toEqual({ r: 127.5, g: 127.5, b: 127.5, a: 1 });
    expect(parseColor("#FF000080").a).toBeCloseTo(0.5, 2);
  });

  it("reads both colour modes from light-dark()", () => {
    expect(modeValue("light-dark(#fff, rgba(1, 2, 3, 0.5))", MODES[0])).toBe("#fff");
    expect(modeValue("light-dark(#fff, rgba(1, 2, 3, 0.5))", MODES[1])).toBe("rgba(1, 2, 3, 0.5)");
  });
});
