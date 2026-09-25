import { redirect } from "next/navigation";
import { OrganizationSkillsPage } from "@/features/skills/organization-skills-page";
import { SpaceSkillsPage } from "@/features/skills/space-skills-page";
import { eneoApi } from "@/lib/api/server";
import { unwrap } from "@/lib/api/errors";
import { hasPermission } from "@/lib/auth/permissions";
import { pageTitle } from "@/lib/page-metadata";

type Props = { params: Promise<{ spaceId: string }> };

// The space layout's title template adds the space name: "Förmågor · Upphandling · Eneo".
export const generateMetadata = pageTitle("skills");

export default async function SkillsRoute({ params }: Props) {
  const { spaceId } = await params;
  if (spaceId === "organization") {
    const user = await unwrap(eneoApi().GET("/api/v1/users/me/"));
    if (!hasPermission(user)("admin")) redirect("/spaces/list");
    return <OrganizationSkillsPage />;
  }
  return <SpaceSkillsPage />;
}
