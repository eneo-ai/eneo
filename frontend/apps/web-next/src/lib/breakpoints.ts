/**
 * Media queries for JavaScript, at the breakpoints Tailwind's `sm:`/`md:`/`lg:`
 * classes use. Tailwind's defaults (rem, so they move with the browser's font
 * size), not the px breakpoints of Astryx's `__adaptations`: a layout chosen in
 * JS then always agrees with the CSS around it. Below a breakpoint is
 * `` `not all and ${MEDIA.md}` ``.
 */
export const MEDIA = {
  sm: "(width >= 40rem)",
  md: "(width >= 48rem)",
  lg: "(width >= 64rem)"
} as const;
