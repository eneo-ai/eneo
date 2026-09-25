import { redirect } from "next/navigation";
import { OrganizationSkillDetailPage } from "@/features/skills/organization-skill-detail-page";
import { eneoApi } from "@/lib/api/server";
import { unwrap } from "@/lib/api/errors";
import { hasPermission } from "@/lib/auth/permissions";
import { pageTitle } from "@/lib/page-metadata";

export const generateMetadata = pageTitle("organization_skills_page_title");

export default async function OrganizationSkillDetailRoute({
  params
}: {
  params: Promise<{ skillId: string }>;
}) {
  const user = await unwrap(eneoApi().GET("/api/v1/users/me/"));
  if (!hasPermission(user)("admin")) redirect("/spaces/list");
  const { skillId } = await params;
  return <OrganizationSkillDetailPage skillId={skillId} />;
}
