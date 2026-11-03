/**
 * WCAG 2.2 contrast maths for the Eneo theme tokens: colour parsing, alpha
 * compositing, relative luminance and the contrast ratio (1.4.3, 1.4.11).
 * Pure functions, shared by the token contrast test and anything else that
 * needs to judge a colour pair.
 */

export const MODES = [
  { name: "light", index: 0 },
  { name: "dark", index: 1 }
] as const;
export type Mode = (typeof MODES)[number];

export type Rgba = { r: number; g: number; b: number; a: number };

/** Splits `light-dark(a, b)` into its two values (commas inside rgba() kept). */
export function modeValue(value: string, mode: Mode): string {
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

export function parseColor(raw: string): Rgba {
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
  throw new Error(`Unsupported colour "${raw}": extend parseColor() in contrast-math.ts`);
}

/** A token's colour in one mode, following `var(--other)` references. */
export function tokenColor(tokens: Record<string, string>, token: string, mode: Mode): Rgba {
  const value = tokens[token];
  if (value === undefined) throw new Error(`Unknown token ${token}`);
  const resolved = modeValue(value, mode);
  const reference = /^var\((--[\w-]+)\)$/.exec(resolved)?.[1];
  return reference ? tokenColor(tokens, reference, mode) : parseColor(resolved);
}

/** Paints `top` over an opaque `bottom`. */
export function over(top: Rgba, bottom: Rgba): Rgba {
  const mix = (a: number, b: number) => a * top.a + b * (1 - top.a);
  return { r: mix(top.r, bottom.r), g: mix(top.g, bottom.g), b: mix(top.b, bottom.b), a: 1 };
}

export function luminance({ r, g, b }: Rgba): number {
  const linear = (channel: number) => {
    const c = channel / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
}

/** WCAG contrast ratio; a translucent foreground is composited over the background first. */
export function contrastRatio(foreground: Rgba, background: Rgba): number {
  const fg = luminance(foreground.a < 1 ? over(foreground, background) : foreground);
  const bg = luminance(background);
  return (Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05);
}
