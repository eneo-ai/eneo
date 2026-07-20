import { redirect } from "@sveltejs/kit";
import { resolve } from "$app/paths";

export const load = async (event) => {
  const { canManage } = await event.parent();
  if (!canManage) {
    redirect(307, resolve("/spaces/organization/skills"));
  }
};
