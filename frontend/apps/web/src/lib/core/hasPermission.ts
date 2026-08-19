import type { Permission, Role } from "@eneo/eneo-js";

const flowPermissionExpansions: Partial<Record<Permission, Permission[]>> = {
  flows: ["flows_view", "flows_run", "flows_manage", "flows_ai_builder"],
  flows_manage: ["flows_view", "flows_run"],
  flows_run: ["flows_view"]
};

export function hasPermission(entity: { roles?: Role[]; predefined_roles?: Role[] }) {
  try {
    const rolePermissons = entity.roles?.flatMap((role) => role.permissions) ?? [];
    const predefPermissions = entity.predefined_roles?.flatMap((role) => role.permissions) ?? [];
    const permissions = [...rolePermissons, ...predefPermissions];
    const expandedPermissions = new Set<Permission>(permissions);
    for (const permission of permissions) {
      const impliedPermissions = flowPermissionExpansions[permission];
      if (!impliedPermissions) continue;
      for (const impliedPermission of impliedPermissions) {
        expandedPermissions.add(impliedPermission);
      }
    }

    return function (
      requiredPermission: { anyOf?: Permission[]; allOf?: Permission[] } | null | Permission
    ) {
      if (requiredPermission === null) return true;
      if (typeof requiredPermission === "string")
        return expandedPermissions.has(requiredPermission);

      const passesAllOf = () => {
        if (!requiredPermission.allOf) return true;
        for (const permission of requiredPermission.allOf) {
          if (!expandedPermissions.has(permission)) {
            return false;
          }
        }
        return true;
      };

      const passesAnyOf = () => {
        if (!requiredPermission.anyOf) return true;
        for (const permission of requiredPermission.anyOf) {
          if (expandedPermissions.has(permission)) {
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
