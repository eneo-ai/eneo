import type { ResourcePermission } from "@eneo/eneo-js";
import { redirect } from "@sveltejs/kit";
import { resolve } from "$app/paths";

const CREATE_SKILL_PERMISSION: ResourcePermission = "create";
const READ_SKILL_PERMISSION: ResourcePermission = "read";

export const load = async (event) => {
  const { currentSpace } = await event.parent();
  if (currentSpace.skill_permissions.includes(CREATE_SKILL_PERMISSION)) return;

  const spaceRouteId = currentSpace.personal
    ? "personal"
    : currentSpace.organization
      ? "organization"
      : currentSpace.id;
  const fallbackPath = currentSpace.skill_permissions.includes(READ_SKILL_PERMISSION)
    ? resolve(`/spaces/${spaceRouteId}/skills`)
    : resolve(`/spaces/${spaceRouteId}/overview`);
  redirect(307, fallbackPath);
};
