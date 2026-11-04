// @ts-check
/**
 * @typedef {"text" | "graphics" | "fail" | "invalid"} ContrastVerdict
 * @typedef {{primary_color?: string | null, header_color?: string | null,
 *   primary_color_dark?: string | null, header_color_dark?: string | null}} ThemeColors
 * @typedef {{light: {accent: string, on_accent: string},
 *   dark: {accent: string, on_accent: string}}} LauncherColors
 */
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
/** @param {string} value
 * @returns {boolean} */
export function isHexColor(value) {
  return HEX_COLOR.test(value.trim());
}
/** The `#RRGGBB` form the API stores: shorthand expanded, upper case.
 * @param {string} value
 * @returns {string} */
export function normalizeHexColor(value) {
  const raw = value.trim().slice(1);
  const full = raw.length === 3 ? [...raw].map((c) => c + c).join("") : raw;
  return `#${full.toUpperCase()}`;
}
/** @param {number} value
 * @returns {number} */
function channel(value) {
  const srgb = value / 255;
  return srgb <= 0.03928 ? srgb / 12.92 : Math.pow((srgb + 0.055) / 1.055, 2.4);
}
/** @param {string} hex
 * @returns {number} */
export function relativeLuminance(hex) {
  const raw = hex.trim().slice(1);
  const full = raw.length === 3 ? [...raw].map((c) => c + c).join("") : raw;
  const r = parseInt(full.slice(0, 2), 16);
  const g = parseInt(full.slice(2, 4), 16);
  const b = parseInt(full.slice(4, 6), 16);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}
/** Contrast ratio between two hex colours, 1..21.
 * @param {string} foreground
 * @param {string} background
 * @returns {number} */
export function contrastRatio(foreground, background) {
  const l1 = relativeLuminance(foreground);
  const l2 = relativeLuminance(background);
  const [light, dark] = l1 >= l2 ? [l1, l2] : [l2, l1];
  return (light + 0.05) / (dark + 0.05);
}
/** How the colour fares against the surface it sits on: white in light mode, the dark panel in dark mode.
 * @param {string} primary
 * @param {string} [surface]
 * @returns {{ ratio: number; verdict: ContrastVerdict }} */
export function contrastVerdict(primary, surface = LIGHT_SURFACE) {
  if (!isHexColor(primary)) return { ratio: 0, verdict: "invalid" };
  const ratio = contrastRatio(primary, surface);
  return {
    ratio,
    verdict: ratio >= 4.5 ? "text" : ratio >= 3 ? "graphics" : "fail"
  };
}
/** Text colour that reads on the given background: white on dark, near-black on light.
 * @param {string} background
 * @returns {"#FFFFFF" | "#111111"} */
export function readableOn(background) {
  if (!isHexColor(background)) return "#111111";
  return contrastRatio("#FFFFFF", background) >= contrastRatio("#111111", background)
    ? "#FFFFFF"
    : "#111111";
}
/** @param {string | null | undefined} colour
 * @returns {string | null} */
function valid(colour) {
  return colour && isHexColor(colour) ? colour : null;
}
/**
 * The accent and header colour to paint for one scheme. Dark mode falls back
 * to the light-mode colours when it has none of its own.
 *
 * @param {ThemeColors} theme
 * @param {boolean} dark
 * @returns {{ accent: string; header: string | null }} */
export function themeColors(theme, dark) {
  const accent =
    (dark ? valid(theme.primary_color_dark) : null) ??
    valid(theme.primary_color) ??
    DEFAULT_PRIMARY_COLOR;
  const header = (dark ? valid(theme.header_color_dark) : null) ?? valid(theme.header_color);
  return { accent, header };
}
/**
 * What the loader paints its launcher button with, per scheme of the host
 * page. A widget pinned to one scheme shows that scheme's colour whatever the
 * host shows, like its panel does.
 *
 * @param {ThemeColors & { color_scheme?: "auto" | "light" | "dark" | null }} theme
 * @returns {LauncherColors} */
export function launcherColors(theme) {
  const pinned = theme.color_scheme === "light" || theme.color_scheme === "dark";
  const light = themeColors(theme, pinned && theme.color_scheme === "dark").accent;
  const dark = themeColors(theme, !pinned || theme.color_scheme === "dark").accent;
  return {
    light: { accent: light, on_accent: readableOn(light) },
    dark: { accent: dark, on_accent: readableOn(dark) }
  };
}
