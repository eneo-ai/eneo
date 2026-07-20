import { redirect } from "@sveltejs/kit";
import { resolve } from "$app/paths";
import { hasPermission } from "$lib/core/hasPermission";

export const load = async (event) => {
  const { user } = await event.parent();
  const userHasPermission = hasPermission(user);
  const canPublish = userHasPermission("admin");
  const canBrowse = canPublish || userHasPermission("skills");
  const canManage =
    canPublish ||
    userHasPermission({
      allOf: ["skills", "skills_management"]
    });

  if (!canBrowse) {
    redirect(307, resolve("/spaces/list"));
  }

  return {
    canManage,
    canPublish
  };
};
