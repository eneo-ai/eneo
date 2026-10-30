import { createFileRoute } from "@tanstack/react-router";
import { SpaceOverview } from "@/features/spaces/overview/space-overview.client";

export const Route = createFileRoute("/_app/spaces/$spaceId/overview")({
  component: SpaceOverview
});
