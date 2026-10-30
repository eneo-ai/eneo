import { createFileRoute } from "@tanstack/react-router";
import { AppsPage } from "@/features/apps/apps-page";
import { spaceTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/spaces/$spaceId/apps/")({
  head: ({ matches, match }) => spaceTitle(matches, match.context.t, match.context.t("apps")),
  remountDeps: ({ params }) => params.spaceId,
  component: AppsPage
});
