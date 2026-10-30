import { createFileRoute } from "@tanstack/react-router";
import { ServicesPage } from "@/features/services/services-page";
import { spaceTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/spaces/$spaceId/services/")({
  head: ({ matches, match }) => spaceTitle(matches, match.context.t, match.context.t("services")),
  remountDeps: ({ params }) => params.spaceId,
  component: ServicesPage
});
