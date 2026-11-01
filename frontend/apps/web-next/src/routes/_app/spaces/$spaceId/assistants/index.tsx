import { createFileRoute, notFound } from "@tanstack/react-router";
import { AssistantsPage } from "@/features/assistants/assistants-page";
import { spaceTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/spaces/$spaceId/assistants/")({
  loader: async ({ parentMatchPromise }) => {
    const { loaderData: space } = await parentMatchPromise;
    if (space?.organization) throw notFound();
  },
  head: ({ matches, match }) => spaceTitle(matches, match.context.t, match.context.t("assistants")),
  remountDeps: ({ params }) => params.spaceId,
  component: AssistantsPage
});
