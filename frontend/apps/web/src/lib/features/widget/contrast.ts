/* eslint-disable eneo/no-raw-color -- WCAG contrast maths needs literal reference colours */
/**
 * WCAG 2.x contrast for the widget's primary colour. The launcher shows a
 * white icon and the visitor's own messages sit on the accent colour, so the
 * colour must reach 3:1 against white for graphics (1.4.11) and 4.5:1 to be
 * safe for text (1.4.3).
 */

export const HEX_COLOR = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i;

/** The backend default for a new widget's primary colour. */
export const DEFAULT_PRIMARY_COLOR = "#1F4E79";
/** The panel background in dark mode; the loader paints the same colour behind the frame. */
export const DARK_SURFACE = "#111111";
export const LIGHT_SURFACE = "#FFFFFF";

export function isHexColor(value: string): boolean {
  return HEX_COLOR.test(value.trim());
}

/** The `#RRGGBB` form the API stores: shorthand expanded, upper case. */
export function normalizeHexColor(value: string): string {
  const raw = value.trim().slice(1);
  const full = raw.length === 3 ? [...raw].map((c) => c + c).join("") : raw;
  return `#${full.toUpperCase()}`;
}

function channel(value: number): number {
  const srgb = value / 255;
  return srgb <= 0.03928 ? srgb / 12.92 : Math.pow((srgb + 0.055) / 1.055, 2.4);
}

export function relativeLuminance(hex: string): number {
  const raw = hex.trim().slice(1);
  const full = raw.length === 3 ? [...raw].map((c) => c + c).join("") : raw;
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16));
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

/** Contrast ratio between two hex colours, 1..21. */
export function contrastRatio(foreground: string, background: string): number {
  const l1 = relativeLuminance(foreground);
  const l2 = relativeLuminance(background);
  const [light, dark] = l1 >= l2 ? [l1, l2] : [l2, l1];
  return (light + 0.05) / (dark + 0.05);
}

export type ContrastVerdict = "text" | "graphics" | "fail" | "invalid";

/** How the colour fares against the surface it sits on: white in light mode, the dark panel in dark mode. */
export function contrastVerdict(
  primary: string,
  surface: string = LIGHT_SURFACE
): { ratio: number; verdict: ContrastVerdict } {
  if (!isHexColor(primary)) return { ratio: 0, verdict: "invalid" };
  const ratio = contrastRatio(primary, surface);
  return {
    ratio,
    verdict: ratio >= 4.5 ? "text" : ratio >= 3 ? "graphics" : "fail"
  };
}

/** Text colour that reads on the given background: white on dark, near-black on light. */
export function readableOn(background: string): "#FFFFFF" | "#111111" {
  if (!isHexColor(background)) return "#111111";
  return contrastRatio("#FFFFFF", background) >= contrastRatio("#111111", background)
    ? "#FFFFFF"
    : "#111111";
}

type ThemeColors = {
  primary_color?: string | null;
  header_color?: string | null;
  primary_color_dark?: string | null;
  header_color_dark?: string | null;
};

function valid(colour: string | null | undefined): string | null {
  return colour && isHexColor(colour) ? colour : null;
}

/**
 * The accent and header colour to paint for one scheme. Dark mode falls back
 * to the light-mode colours when it has none of its own.
 */
export function themeColors(
  theme: ThemeColors,
  dark: boolean
): { accent: string; header: string | null } {
  const accent =
    (dark ? valid(theme.primary_color_dark) : null) ??
    valid(theme.primary_color) ??
    DEFAULT_PRIMARY_COLOR;
  const header = (dark ? valid(theme.header_color_dark) : null) ?? valid(theme.header_color);
  return { accent, header };
}

export type LauncherColors = {
  light: { accent: string; on_accent: string };
  dark: { accent: string; on_accent: string };
};

/** What the loader paints its launcher button with, per scheme. */
export function launcherColors(theme: ThemeColors): LauncherColors {
  const light = themeColors(theme, false).accent;
  const dark = themeColors(theme, true).accent;
  return {
    light: { accent: light, on_accent: readableOn(light) },
    dark: { accent: dark, on_accent: readableOn(dark) }
  };
}
