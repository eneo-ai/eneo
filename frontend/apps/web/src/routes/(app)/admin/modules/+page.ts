import { hasPermission } from "$lib/core/hasPermission.js";
import { redirect } from "@sveltejs/kit";

export const load = async (event) => {
  const { user } = await event.parent();
  if (!hasPermission(user)("modules")) redirect(302, "/admin");
};
