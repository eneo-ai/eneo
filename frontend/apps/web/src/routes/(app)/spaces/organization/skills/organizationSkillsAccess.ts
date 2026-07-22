import type { ResourcePermission } from "@eneo/eneo-js";
import type { SpaceMenuResource } from "../../[spaceId]/SpaceMenu.svelte";

export type OrganizationSkillsAccess = {
  canBrowse: boolean;
  canManage: boolean;
  canPublish: boolean;
};

export function resolveOrganizationSkillsAccess({
  admin
}: {
  admin: boolean;
}): OrganizationSkillsAccess {
  return {
    canBrowse: admin,
    canManage: admin,
    canPublish: admin
  };
}

export function hasOrganizationNavigationPermission(
  access: OrganizationSkillsAccess,
  action: ResourcePermission,
  resource: SpaceMenuResource
): boolean {
  if (!access.canManage) return false;
  if (resource === "skill") return action === "read";
  if (resource === "website" || resource === "collection") return action === "read";
  return resource === "space" && action === "edit";
}
