import type { SpaceRoleValue } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";

/** Each role includes everything the roles ranked below it can do. */
export const ROLE_RANK = {
  viewer: 1,
  editor: 2,
  admin: 3
} as const satisfies Record<SpaceRoleValue, number>;

/** Every role, lowest first. */
export const SPACE_ROLES = [
  "viewer",
  "editor",
  "admin"
] as const satisfies readonly SpaceRoleValue[];

/** `roles` ordered lowest first, without changing the input. */
export function sortRolesAscending(roles: readonly SpaceRoleValue[]): SpaceRoleValue[] {
  return [...roles].sort((a, b) => ROLE_RANK[a] - ROLE_RANK[b]);
}

/** The lowest of `roles`, or undefined when there are none. */
export function lowestRole(roles: readonly SpaceRoleValue[]): SpaceRoleValue | undefined {
  return sortRolesAscending(roles)[0];
}

/** The role's name as the UI shows it; the API's own labels are English only. */
export function spaceRoleLabel(role: SpaceRoleValue): string {
  switch (role) {
    case "admin":
      return m.space_role_admin();
    case "editor":
      return m.space_role_editor();
    case "viewer":
      return m.space_role_viewer();
    default:
      return role satisfies never;
  }
}

/** One sentence on what the role may do in a space. */
export function spaceRoleDescription(role: SpaceRoleValue): string {
  switch (role) {
    case "admin":
      return m.space_role_admin_description();
    case "editor":
      return m.space_role_editor_description();
    case "viewer":
      return m.space_role_viewer_description();
    default:
      return role satisfies never;
  }
}
