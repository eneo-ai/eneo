import { redirect } from "@sveltejs/kit";
import { resolve } from "$app/paths";
import { hasPermission } from "$lib/core/hasPermission";

export const load = async (event) => {
  const { user } = await event.parent();
  const userHasPermission = hasPermission(user);
  if (!userHasPermission("admin")) {
    redirect(307, resolve("/spaces/list"));
  }
};
