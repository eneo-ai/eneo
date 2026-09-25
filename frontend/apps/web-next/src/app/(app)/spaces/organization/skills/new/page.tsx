import { redirect } from "next/navigation";
import { OrganizationSkillNewPage } from "@/features/skills/organization-skill-new-page";
import { eneoApi } from "@/lib/api/server";
import { unwrap } from "@/lib/api/errors";
import { hasPermission } from "@/lib/auth/permissions";
import { pageTitle } from "@/lib/page-metadata";

export const generateMetadata = pageTitle("organization_skills_new_page_title");

export default async function OrganizationSkillNewRoute() {
  const user = await unwrap(eneoApi().GET("/api/v1/users/me/"));
  if (!hasPermission(user)("admin")) redirect("/spaces/list");
  return <OrganizationSkillNewPage />;
}
