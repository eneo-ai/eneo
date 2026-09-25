import { entityTone, type EntityTone } from "@/lib/entity-accent";
import type { SpaceMember, SpaceRoleValue } from "../space";

/**
 * Astryx Avatar paints its initials on an inner `.astryx-avatar-fallback`
 * element, so the categorical tone targets that element. Full static strings
 * keep Tailwind's JIT from dropping them (never build `bg-ax-${hue}`).
 */
const PERSON_TONE_CLASSES: Record<EntityTone, string> = {
  blue: "[&_.astryx-avatar-fallback]:bg-ax-blue-muted [&_.astryx-avatar-fallback]:text-ax-blue",
  teal: "[&_.astryx-avatar-fallback]:bg-ax-teal-muted [&_.astryx-avatar-fallback]:text-ax-teal",
  purple:
    "[&_.astryx-avatar-fallback]:bg-ax-purple-muted [&_.astryx-avatar-fallback]:text-ax-purple",
  amber:
    "[&_.astryx-avatar-fallback]:bg-ax-orange-muted [&_.astryx-avatar-fallback]:text-ax-orange",
  rose: "[&_.astryx-avatar-fallback]:bg-ax-pink-muted [&_.astryx-avatar-fallback]:text-ax-pink"
};

/** Deterministic initials colour for a person, from the same palette as entity tiles. */
export function personToneClass(id: string): string {
  return PERSON_TONE_CLASSES[entityTone(id)];
}

/** The name the members page shows for a member: their e-mail address. */
export function memberDisplayName(member: Pick<SpaceMember, "email">): string {
  return member.email;
}

/** Translation keys for the space roles (the API only returns English labels). */
export const SPACE_ROLE_LABEL_KEYS: Record<SpaceRoleValue, string> = {
  admin: "space_role_admin",
  editor: "space_role_editor",
  viewer: "space_role_viewer"
};

const ROLE_ORDER: Record<SpaceRoleValue, number> = { admin: 0, editor: 1, viewer: 2 };

/**
 * Admins first, then editors, then viewers; alphabetical within a role, by
 * `compare` (Astryx `useCollator().compare`).
 */
export function sortMembersByRole<T extends Pick<SpaceMember, "email" | "role">>(
  members: readonly T[],
  compare: (a: string, b: string) => number
): T[] {
  return [...members].sort(
    (a, b) => ROLE_ORDER[a.role] - ROLE_ORDER[b.role] || compare(a.email, b.email)
  );
}
