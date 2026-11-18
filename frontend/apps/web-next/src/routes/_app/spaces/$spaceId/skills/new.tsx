import { createFileRoute, redirect } from "@tanstack/react-router";
import { OrganizationSkillNewPage } from "@/features/skills/organization-skill-new-page";
import { SpaceSkillNewPage } from "@/features/skills/space-skill-new-page";
import { spaceQueryOptions } from "@/features/spaces/space";
import { browserApi } from "@/lib/api/browser";
import { readFresh } from "@/lib/api/query";
import { spaceTitle } from "@/lib/route-head";
import { notFoundOn404 } from "@/lib/route-helpers";

export const Route = createFileRoute("/_app/spaces/$spaceId/skills/new")({
  beforeLoad: async ({ context, params }) => {
    // The parent space route checks organization administrators.
    if (params.spaceId === "organization") return;
    const space = await notFoundOn404(
      readFresh(context.queryClient, spaceQueryOptions(browserApi, params.spaceId))
    );
    if (!space.skill_permissions.includes("create"))
      throw redirect({
        href: space.skill_permissions.includes("read")
          ? `/spaces/${params.spaceId}/skills`
          : `/spaces/${params.spaceId}/overview`,
        replace: true
      });
  },
  head: ({ matches, match }) =>
    spaceTitle(matches, match.context.t, match.context.t("skills_library_new_heading")),
  remountDeps: ({ params }) => params.spaceId,
  component: NewSkillPage
});

function NewSkillPage() {
  const { spaceId } = Route.useParams();
  return spaceId === "organization" ? <OrganizationSkillNewPage /> : <SpaceSkillNewPage />;
}
