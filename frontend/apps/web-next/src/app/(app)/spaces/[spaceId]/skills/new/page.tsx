import { redirect } from "next/navigation";
import { OrganizationSkillNewPage } from "@/features/skills/organization-skill-new-page";
import { SpaceSkillNewPage } from "@/features/skills/space-skill-new-page";
import { eneoApi } from "@/lib/api/server";
import { unwrap } from "@/lib/api/errors";
import { hasPermission } from "@/lib/auth/permissions";
import { pageTitle } from "@/lib/page-metadata";
import { spaceQueryOptions } from "@/features/spaces/space";
import { getQueryClient } from "@/lib/api/query";

type Props = { params: Promise<{ spaceId: string }> };

export async function generateMetadata({ params }: Props) {
  const { spaceId } = await params;
  return pageTitle(
    spaceId === "organization"
      ? "organization_skills_new_page_title"
      : "skills_library_new_page_title"
  )();
}

export default async function NewSkillRoute({ params }: Props) {
  const { spaceId } = await params;
  if (spaceId === "organization") {
    const user = await unwrap(eneoApi().GET("/api/v1/users/me/"));
    if (!hasPermission(user)("admin")) redirect("/spaces/list");
    return <OrganizationSkillNewPage />;
  }
  const space = await getQueryClient().fetchQuery(spaceQueryOptions(eneoApi(), spaceId));
  if (!space.skill_permissions.includes("create"))
    redirect(
      space.skill_permissions.includes("read")
        ? `/spaces/${spaceId}/skills`
        : `/spaces/${spaceId}/overview`
    );
  return <SpaceSkillNewPage />;
}
