import type { ResourcePermission } from "@eneo/eneo-js";
import type { SpaceMenuResource } from "../../[spaceId]/SpaceMenu.svelte";

export function hasOrganizationNavigationPermission(
  admin: boolean,
  action: ResourcePermission,
  resource: SpaceMenuResource
): boolean {
  if (!admin) return false;
  if (resource === "skill") return action === "read";
  if (resource === "website" || resource === "collection") return action === "read";
  return resource === "space" && action === "edit";
}
