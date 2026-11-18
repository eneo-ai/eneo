import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/spaces/$spaceId/knowledge/integrations/")({
  beforeLoad: ({ params }) => {
    throw redirect({ href: `/spaces/${params.spaceId}/knowledge?tab=integrations` });
  }
});
