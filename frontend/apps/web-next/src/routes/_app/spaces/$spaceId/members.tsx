import { createFileRoute } from "@tanstack/react-router";
import { SpaceMembers } from "@/features/spaces/members/space-members";
import { spaceTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/spaces/$spaceId/members")({
  head: ({ matches, match }) => spaceTitle(matches, match.context.t, match.context.t("members")),
  component: SpaceMembers
});
