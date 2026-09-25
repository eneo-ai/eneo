import { redirect } from "next/navigation";
import { pageTitle } from "@/lib/page-metadata";
import { eneoApi } from "@/lib/api/server";
import { unwrap } from "@/lib/api/errors";
import { hasPermission } from "@/lib/auth/permissions";
import { OrganizationSkillsPage } from "@/features/skills/organization-skills-page";

export const generateMetadata = pageTitle("organization_skills_page_title");

export default async function OrganizationSkillsRoute() {
  const user = await unwrap(eneoApi().GET("/api/v1/users/me/"));
  if (!hasPermission(user)("admin")) redirect("/spaces/list");
  return <OrganizationSkillsPage />;
}
