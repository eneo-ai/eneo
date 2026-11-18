import { createFileRoute } from "@tanstack/react-router";
import { SpaceSettings } from "@/features/spaces/settings/space-settings";
import { spaceTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/spaces/$spaceId/settings")({
  head: ({ matches, match }) => spaceTitle(matches, match.context.t, match.context.t("settings")),
  remountDeps: ({ params }) => params.spaceId,
  component: SpaceSettings
});
