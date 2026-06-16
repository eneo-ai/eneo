/**
 * Deterministic accent for an entity (assistant, group chat, space): the same
 * id always maps to the same colour, giving browse surfaces visual identity
 * without per-entity config. Uses the theme-aware chart-* tokens (lint-safe,
 * never raw colours). The classes are full static strings so Tailwind's JIT
 * keeps them — never build `bg-chart-${n}` dynamically.
 */
const ACCENTS = [
  "bg-chart-1/15 text-chart-1",
  "bg-chart-2/15 text-chart-2",
  "bg-chart-3/15 text-chart-3",
  "bg-chart-4/15 text-chart-4",
  "bg-chart-5/15 text-chart-5"
] as const;

export function entityAccent(id: string): string {
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  }
  return ACCENTS[hash % ACCENTS.length]!;
}
