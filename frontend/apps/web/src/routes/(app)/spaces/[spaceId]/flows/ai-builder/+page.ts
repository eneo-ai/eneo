import { error } from "@sveltejs/kit";
import { hasPermission } from "$lib/core/hasPermission";

export const ssr = false;

export const load = async (event) => {
  const { intric, currentSpace, user } = await event.parent();

  const isOrgSpace = currentSpace.organization === true;
  if (isOrgSpace) {
    throw error(404);
  }

  if (!hasPermission(user)({ allOf: ["flows_manage", "flows_ai_builder"] })) {
    throw error(403);
  }

  return { intric, currentSpace };
};
