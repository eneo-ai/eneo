import { createFileRoute } from "@tanstack/react-router";
import { OrganizationSkillsPage } from "@/features/skills/organization-skills-page";
import { SpaceSkillsPage } from "@/features/skills/space-skills-page";
import { spaceTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/spaces/$spaceId/skills/")({
  head: ({ matches, match }) => spaceTitle(matches, match.context.t, match.context.t("skills")),
  remountDeps: ({ params }) => params.spaceId,
  component: SkillsPage
});

function SkillsPage() {
  const { spaceId } = Route.useParams();
  return spaceId === "organization" ? <OrganizationSkillsPage /> : <SpaceSkillsPage />;
}
