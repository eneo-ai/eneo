import { redirect } from "next/navigation";
import { OrganizationSkillDetailPage } from "@/features/skills/organization-skill-detail-page";
import { SpaceSkillDetailPage } from "@/features/skills/space-skill-detail-page";
import { eneoApi } from "@/lib/api/server";
import { unwrap } from "@/lib/api/errors";
import { hasPermission } from "@/lib/auth/permissions";
import { pageTitle } from "@/lib/page-metadata";

type Props = { params: Promise<{ spaceId: string; skillId: string }> };

// The space layout's title template adds the space name: "Skills · Upphandling · Eneo".
export const generateMetadata = pageTitle("skills");

export default async function SkillDetailRoute({ params }: Props) {
  const { spaceId, skillId } = await params;
  if (spaceId === "organization") {
    const user = await unwrap(eneoApi().GET("/api/v1/users/me/"));
    if (!hasPermission(user)("admin")) redirect("/spaces/list");
    return <OrganizationSkillDetailPage skillId={skillId} />;
  }
  return <SpaceSkillDetailPage skillId={skillId} />;
}
