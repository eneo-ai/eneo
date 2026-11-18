import { createFileRoute } from "@tanstack/react-router";
import { OrganizationSkillDetailPage } from "@/features/skills/organization-skill-detail-page";
import { SpaceSkillDetailPage } from "@/features/skills/space-skill-detail-page";
import { spaceTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/spaces/$spaceId/skills/$skillId")({
  head: ({ matches, match }) => spaceTitle(matches, match.context.t, match.context.t("skills")),
  remountDeps: ({ params }) => [params.spaceId, params.skillId],
  component: SkillDetailPage
});

function SkillDetailPage() {
  const { spaceId, skillId } = Route.useParams();
  return spaceId === "organization" ? (
    <OrganizationSkillDetailPage skillId={skillId} />
  ) : (
    <SpaceSkillDetailPage skillId={skillId} />
  );
}
