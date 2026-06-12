import type { Schema } from "@/lib/api/models";

export type Permission = Schema<"Permission">;

type RoleLike = { permissions?: Permission[] | null };

/**
 * A permission requirement: a single permission, a combination (all listed
 * `allOf` AND at least one of `anyOf`), or null for "always allowed".
 */
export type PermissionRequirement =
  | Permission
  | { anyOf?: Permission[]; allOf?: Permission[] }
  | null;

/**
 * Flattens a user's roles into the effective permission set. The backend
 * folds predefined roles into `roles` (marked via predefined_source), but
 * older payload shapes with a separate `predefined_roles` list are accepted
 * too.
 */
export function collectPermissions(user: {
  roles?: RoleLike[] | null;
  predefined_roles?: RoleLike[] | null;
}): Permission[] {
  return [...(user.roles ?? []), ...(user.predefined_roles ?? [])].flatMap(
    (role) => role.permissions ?? []
  );
}

/** Checks a requirement against an explicit permission set. */
export function checkPermission(
  permissions: Permission[],
  required: PermissionRequirement
): boolean {
  if (required === null) return true;
  if (typeof required === "string") return permissions.includes(required);

  const passesAllOf = (required.allOf ?? []).every((permission) =>
    permissions.includes(permission)
  );
  const passesAnyOf = required.anyOf
    ? required.anyOf.some((permission) => permissions.includes(permission))
    : true;

  return passesAllOf && passesAnyOf;
}

/**
 * Port of the Svelte app's hasPermission: builds a checker bound to the
 * user's flattened role permissions.
 */
export function hasPermission(user: {
  roles?: RoleLike[] | null;
  predefined_roles?: RoleLike[] | null;
}): (required: PermissionRequirement) => boolean {
  const permissions = collectPermissions(user);
  return (required) => checkPermission(permissions, required);
}
