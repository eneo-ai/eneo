import type { ResourcePermission } from "@eneo/eneo-js";
import type { SpaceMenuResource } from "../../[spaceId]/SpaceMenu.svelte";

export type OrganizationSkillsAccess = {
  canBrowse: boolean;
  canManage: boolean;
  canPublish: boolean;
};

export function resolveOrganizationSkillsAccess({
  admin,
  skills,
  skillsManagement
}: {
  admin: boolean;
  skills: boolean;
  skillsManagement: boolean;
}): OrganizationSkillsAccess {
  return {
    canBrowse: admin || skills,
    canManage: admin || (skills && skillsManagement),
    canPublish: admin
  };
}

/**
 * Projects tenant capabilities into navigation visibility only. Every linked
 * destination performs its own server-side authorization. Delegated users
 * cannot load the admin-only organisation Space, so this cannot depend on its
 * SpaceActor projection without hiding the catalogue they are allowed to use.
 */
export function hasOrganizationNavigationPermission(
  access: OrganizationSkillsAccess,
  action: ResourcePermission,
  resource: SpaceMenuResource
): boolean {
  if (resource === "skill") return action === "read" && access.canBrowse;
  if (!access.canPublish) return false;
  if (resource === "website" || resource === "collection") return action === "read";
  return resource === "space" && action === "edit";
}
