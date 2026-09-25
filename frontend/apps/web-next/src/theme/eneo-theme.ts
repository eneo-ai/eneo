/* eslint-disable eneo/no-raw-color -- the theme definition is the one place raw colour values live */
/**
 * Eneo theme for Astryx: the single source of truth for web-next colours,
 * radii, shadows and fonts. It extends Astryx Neutral (typography scale 14px /
 * 1.2, motion, component overrides, lucide icon registry) and overrides the
 * values from the approved Eneo design canvas.
 *
 * Contrast is a requirement, not a preference (WCAG 2.2 AA, ACCESSIBILITY.md):
 * text 4.5:1 and control boundaries, focus ring, icons and status dots 3:1 on
 * every surface they are used on. src/theme/eneo-theme.contrast.test.ts checks
 * the documented pairs in both colour modes; add a pair there when you add a
 * token or use one on a new surface.
 *
 * Built, never injected: after editing run `bun run theme:build`, which writes
 * eneo.css / eneo.js / eneo.d.ts next to this file. The runtime Theme skips
 * <style> injection for built themes, so the production CSP stays nonce-only.
 * `bun run lint` fails when the generated files are stale.
 *
 * The shadcn variables in src/app/globals.css (--background, --primary, …)
 * point at these tokens, and the `ax-*` Tailwind bridge exposes them as
 * utilities. See AGENTS.md for the mapping.
 */
import { defineTheme } from "@astryxdesign/core/theme";
import { neutralTheme } from "@astryxdesign/theme-neutral";
import { neutralIconRegistry } from "@astryxdesign/theme-neutral/built";

const FONT_BODY =
  'var(--font-figtree, Figtree), -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif';
const FONT_CODE =
  'var(--font-jetbrains-mono, "JetBrains Mono"), ui-monospace, "SF Mono", Monaco, Consolas, "Liberation Mono", "Courier New", monospace';

// Categorical hues for entity tiles (spaces, assistants), charts and badges.
// Eneo "amber" lives on Astryx's orange family and "rose" on pink.
const categorical = {
  blue: {
    fg: ["#1557A8", "#8DBAF7"],
    icon: ["#1A6FD2", "#4D94F2"],
    bg: ["#E6EEFA", "rgba(77, 148, 242, 0.16)"]
  },
  teal: {
    fg: ["#0B6E69", "#52D1C6"],
    icon: ["#0B6E69", "#52D1C6"],
    bg: ["#DCF2EF", "rgba(82, 209, 198, 0.14)"]
  },
  purple: {
    fg: ["#6D46B8", "#B99AF5"],
    icon: ["#6D46B8", "#B99AF5"],
    bg: ["#EEE7FA", "rgba(185, 154, 245, 0.16)"]
  },
  orange: {
    fg: ["#94590A", "#F1B45C"],
    icon: ["#94590A", "#F1B45C"],
    bg: ["#FBEEDB", "rgba(241, 180, 92, 0.14)"]
  },
  pink: {
    fg: ["#B03A5B", "#F495B6"],
    icon: ["#B03A5B", "#F495B6"],
    bg: ["#FBE4EA", "rgba(244, 149, 182, 0.14)"]
  },
  // Status-aligned hues so Badge/Token colours match the status palette.
  green: {
    fg: ["#1E7A32", "#6CC382"],
    icon: ["#1E7A32", "#6CC382"],
    bg: ["#E2F2E5", "rgba(108, 195, 130, 0.15)"]
  },
  yellow: {
    fg: ["#8A5A00", "#E9B949"],
    icon: ["#8A5A00", "#E9B949"],
    bg: ["#FCF0D4", "rgba(233, 185, 73, 0.15)"]
  },
  red: {
    fg: ["#B42330", "#FF8177"],
    icon: ["#B42330", "#FF8177"],
    bg: ["#FBE5E6", "rgba(255, 129, 119, 0.15)"]
  }
} as const satisfies Record<string, Record<"fg" | "icon" | "bg", readonly [string, string]>>;

function hueTokens(hue: keyof typeof categorical) {
  const { fg, icon, bg } = categorical[hue];
  return {
    [`--color-text-${hue}`]: [fg[0], fg[1]],
    [`--color-icon-${hue}`]: [icon[0], icon[1]],
    [`--color-background-${hue}`]: [bg[0], bg[1]]
  } as Record<`--color-${"text" | "icon" | "background"}-${typeof hue}`, [string, string]>;
}

export const eneoTheme = defineTheme({
  name: "eneo",
  extends: neutralTheme,
  // Named import so `astryx theme build` emits it into the built module.
  icons: neutralIconRegistry,

  tokens: {
    // Surfaces: body (app background behind the page panel) → surface → card → popover.
    "--color-background-body": ["#ECEEF2", "#07080B"],
    "--color-background-surface": ["#FFFFFF", "#111419"],
    "--color-background-card": ["#FFFFFF", "#161A20"],
    "--color-background-popover": ["#FFFFFF", "#1C2027"],
    "--color-background-muted": ["#F2F3F6", "#1C2027"],
    "--color-background-inverted": ["#0F1217", "#F1F3F6"],

    // Text and icons.
    "--color-text-primary": ["#0F1217", "#F1F3F6"],
    "--color-text-secondary": ["#535A67", "#AEB5C1"],
    "--color-text-disabled": ["#9AA0AB", "#5C6470"],
    "--color-text-accent": ["#1557A8", "#8DBAF7"],
    "--color-icon-primary": ["#0F1217", "#F1F3F6"],
    "--color-icon-secondary": ["#6B7280", "#8B93A1"],
    "--color-icon-disabled": ["#9AA0AB", "#5C6470"],
    "--color-icon-accent": ["#1A6FD2", "#4D94F2"],

    // Accent (Eneo blue). Owning the accent means owning its on-colour too.
    "--color-accent": ["#1A6FD2", "#4D94F2"],
    "--color-on-accent": ["#FFFFFF", "#06101C"],
    "--color-accent-muted": ["#E6EEFA", "rgba(77, 148, 242, 0.16)"],

    // Neutral tints: selected rows/nav items, hover and pressed overlays, scrim.
    "--color-neutral": ["rgba(15, 18, 23, 0.07)", "rgba(255, 255, 255, 0.08)"],
    "--color-overlay-hover": ["rgba(15, 18, 23, 0.045)", "rgba(255, 255, 255, 0.05)"],
    "--color-overlay-pressed": ["rgba(15, 18, 23, 0.09)", "rgba(255, 255, 255, 0.1)"],
    "--color-overlay": ["rgba(15, 18, 23, 0.4)", "rgba(0, 0, 0, 0.6)"],

    // Borders. Both are decorative (dividers, card and container edges) and
    // below 3:1: never the only boundary of a form control. Controls use
    // --eneo-color-border-control (localTokens and `components` below).
    "--color-border": ["rgba(15, 18, 23, 0.09)", "rgba(255, 255, 255, 0.08)"],
    "--color-border-emphasized": ["#D3D7DE", "#2C323B"],

    // Status.
    "--color-success": ["#1E7A32", "#6CC382"],
    "--color-success-muted": ["#E2F2E5", "rgba(108, 195, 130, 0.15)"],
    "--color-on-success": ["#FFFFFF", "#06101C"],
    "--color-warning": ["#8A5A00", "#E9B949"],
    "--color-warning-muted": ["#FCF0D4", "rgba(233, 185, 73, 0.15)"],
    "--color-on-warning": ["#FFFFFF", "#06101C"],
    "--color-error": ["#B42330", "#FF8177"],
    "--color-error-muted": ["#FBE5E6", "rgba(255, 129, 119, 0.15)"],
    "--color-on-error": ["#FFFFFF", "#06101C"],

    // Effects.
    "--color-skeleton": ["#E6E9EE", "#242A32"],
    "--color-track": ["#DDE1E7", "#2C323B"],
    "--color-shadow": ["rgba(0, 0, 0, 0.08)", "rgba(0, 0, 0, 0.4)"],

    ...hueTokens("blue"),
    ...hueTokens("teal"),
    ...hueTokens("purple"),
    ...hueTokens("orange"),
    ...hueTokens("pink"),
    ...hueTokens("green"),
    ...hueTokens("yellow"),
    ...hueTokens("red"),

    // Shape: inner 6 · element (buttons, inputs) 10 · container (cards) 12 ·
    // page panel 18 · chat composer 20 · pill.
    "--radius-none": "0px",
    "--radius-inner": "0.375rem",
    "--radius-element": "0.625rem",
    "--radius-container": "0.75rem",
    "--radius-page": "1.125rem",
    "--radius-chat": "1.25rem",
    "--radius-full": "9999px",

    // Elevation: soft layered drops; dark mode adds a 1px white inset rim.
    // Shadows are not colours, so each colour stop carries its own light-dark().
    "--shadow-low":
      "0 1px 2px light-dark(rgba(0, 0, 0, 0.04), rgba(0, 0, 0, 0.3)), " +
      "0 3px 8px light-dark(rgba(0, 0, 0, 0.06), rgba(0, 0, 0, 0.35)), " +
      "inset 0 0 0 1px light-dark(transparent, rgba(255, 255, 255, 0.05))",
    "--shadow-med":
      "0 2px 4px light-dark(rgba(0, 0, 0, 0.05), rgba(0, 0, 0, 0.35)), " +
      "0 8px 20px light-dark(rgba(0, 0, 0, 0.08), rgba(0, 0, 0, 0.45)), " +
      "inset 0 0 0 1px light-dark(transparent, rgba(255, 255, 255, 0.07))",
    "--shadow-high":
      "0 4px 8px light-dark(rgba(0, 0, 0, 0.08), rgba(0, 0, 0, 0.45)), " +
      "0 24px 56px light-dark(rgba(0, 0, 0, 0.2), rgba(0, 0, 0, 0.6)), " +
      "inset 0 0 0 1px light-dark(transparent, rgba(255, 255, 255, 0.09))",

    // Fonts are loaded by next/font in src/app/layout.tsx (CSS variables on <html>).
    "--font-family-body": FONT_BODY,
    "--font-family-heading": FONT_BODY,
    "--font-family-code": FONT_CODE
  },

  localTokens: {
    // Eneo-only roles without an Astryx equivalent.
    "--eneo-color-background-sunken": ["#F8F9FB", "#0D1014"],
    // Tertiary text: 4.5:1 on every surface and on hover/selected rows over
    // surface, card and popover (was #6B7280 / #8B93A1: 4.16:1 on body).
    "--eneo-color-text-tertiary": ["#646A77", "#939BA8"],
    // Boundary of form controls (inputs, selects, checkboxes, radios, switch
    // tracks): 3:1 on every surface, WCAG 1.4.11. The emphasized border above
    // stays the lighter, decorative edge.
    "--eneo-color-border-control": ["#7E8593", "#747C8B"],
    // Neutral paints Badge/StatusDot/ProgressBar status fills from these; point
    // them at the Eneo status colours so fills pair with the on-* colours above.
    "--astryx-theme-neutral-color-status-fill-accent": ["#1A6FD2", "#4D94F2"],
    "--astryx-theme-neutral-color-status-fill-success": ["#1E7A32", "#6CC382"],
    "--astryx-theme-neutral-color-status-fill-warning": ["#8A5A00", "#E9B949"],
    "--astryx-theme-neutral-color-status-fill-error": ["#B42330", "#FF8177"],
    "--astryx-theme-neutral-color-status-muted-accent": ["#E6EEFA", "rgba(77, 148, 242, 0.16)"]
  },

  // Astryx draws form-control boundaries with --color-border-emphasized (and
  // the unchecked switch track with --color-background-gray, which Neutral
  // points at it). Re-point them to the control border inside the controls
  // only, so dividers and container edges keep the lighter border.
  components: {
    ...Object.fromEntries(
      [
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
      ].map((key) => [
        key,
        { base: { "--color-border-emphasized": "var(--eneo-color-border-control)" } }
      ])
    ),
    switch: {
      base: { "--color-background-gray": "var(--eneo-color-border-control)" }
    }
  }
});
