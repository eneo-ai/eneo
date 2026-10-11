import { m } from "$lib/paraglide/messages";

/** A security class as the organisation defined it: Eneo ships no fixed set. */
export type NamedSecurityLevel = { name: string; security_level: number };

/** The organisation's name for a level; the bare level only when no class has it. */
export function securityClassName(classes: readonly NamedSecurityLevel[], level: number): string {
  return (
    classes.find((entry) => entry.security_level === level)?.name ??
    m.flow_classification_unnamed_level({ level: String(level) })
  );
}

export type SecurityClassStanding = "highest" | "between" | "lowest";

/**
 * Where a level stands among the organisation's classes. Null when there is
 * nothing to compare it with: no class, or one.
 */
export function securityClassStanding(
  classes: readonly NamedSecurityLevel[],
  level: number
): SecurityClassStanding | null {
  if (classes.length < 2) return null;
  const levels = classes.map((entry) => entry.security_level);
  if (level >= Math.max(...levels)) return "highest";
  if (level <= Math.min(...levels)) return "lowest";
  return "between";
}
