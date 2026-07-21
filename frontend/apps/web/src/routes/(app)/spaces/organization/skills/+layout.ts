import { redirect } from "@sveltejs/kit";
import { resolve } from "$app/paths";
import { hasPermission } from "$lib/core/hasPermission";
import { resolveOrganizationSkillsAccess } from "./organizationSkillsAccess";

export const load = async (event) => {
  const { user } = await event.parent();
  const userHasPermission = hasPermission(user);
  const access = resolveOrganizationSkillsAccess({
    admin: userHasPermission("admin"),
    skills: userHasPermission("skills"),
    skillsManagement: userHasPermission("skills_management")
  });

  if (!access.canBrowse) {
    redirect(307, resolve("/spaces/list"));
  }

  return {
    canManage: access.canManage,
    canPublish: access.canPublish
  };
};
