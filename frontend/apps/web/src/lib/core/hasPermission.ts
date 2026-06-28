import type { Permission, Role } from "@eneo/eneo-js";

export function hasPermission(entity: { roles?: Role[]; predefined_roles?: Role[] }) {
  try {
    const rolePermissons = entity.roles?.flatMap((role) => role.permissions) ?? [];
    const predefPermissions = entity.predefined_roles?.flatMap((role) => role.permissions) ?? [];
    const permissions = [...rolePermissons, ...predefPermissions];

    return function (
      requiredPermission: { anyOf?: Permission[]; allOf?: Permission[] } | null | Permission
    ) {
      if (requiredPermission === null) return true;
      if (typeof requiredPermission === "string") return permissions.includes(requiredPermission);

      const passesAllOf = () => {
        if (!requiredPermission.allOf) return true;
        for (const permission of requiredPermission.allOf) {
          if (!permissions.includes(permission)) {
            return false;
          }
        }
        return true;
      };

      const passesAnyOf = () => {
        if (!requiredPermission.anyOf) return true;
        for (const permission of requiredPermission.anyOf) {
          if (permissions.includes(permission)) {
            return true;
          }
        }
        return false;
      };

      return passesAllOf() && passesAnyOf();
    };
  } catch (e) {
    console.error("some weird perm error");
    throw e;
  }
}
