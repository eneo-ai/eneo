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

export function isHexColor(value: string): boolean {
  return HEX_COLOR.test(value.trim());
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

/** How the colour fares against white, the launcher icon and message text colour. */
export function contrastVerdict(primary: string): { ratio: number; verdict: ContrastVerdict } {
  if (!isHexColor(primary)) return { ratio: 0, verdict: "invalid" };
  const ratio = contrastRatio(primary, "#ffffff");
  return {
    ratio,
    verdict: ratio >= 4.5 ? "text" : ratio >= 3 ? "graphics" : "fail"
  };
}
