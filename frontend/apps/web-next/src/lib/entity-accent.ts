/**
 * Deterministic categorical colour for an entity (assistant, group chat,
 * space): the same id always maps to the same tone, giving browse surfaces
 * visual identity without per-entity config. Tones are the Eneo categorical
 * palette from the Astryx theme (src/theme/eneo-theme.ts) — muted background
 * plus an AA-contrast foreground in both colour modes.
 *
 * The classes are full static strings so Tailwind's JIT keeps them — never
 * build `bg-ax-${hue}` dynamically.
 */
export const ENTITY_TONES = ["blue", "teal", "purple", "amber", "rose"] as const;
export type EntityTone = (typeof ENTITY_TONES)[number];

// Eneo "amber" and "rose" are Astryx's orange and pink hue families.
export const ENTITY_TONE_CLASSES: Record<EntityTone, string> = {
  blue: "bg-ax-blue-muted text-ax-blue",
  teal: "bg-ax-teal-muted text-ax-teal",
  purple: "bg-ax-purple-muted text-ax-purple",
  amber: "bg-ax-orange-muted text-ax-orange",
  rose: "bg-ax-pink-muted text-ax-pink"
};

/** The tone for an id (or any stable key such as a name). */
export function entityTone(id: string): EntityTone {
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  }
  return ENTITY_TONES[hash % ENTITY_TONES.length]!;
}

/** Background + foreground classes for an entity's tone. */
export function entityAccent(id: string): string {
  return ENTITY_TONE_CLASSES[entityTone(id)];
}
