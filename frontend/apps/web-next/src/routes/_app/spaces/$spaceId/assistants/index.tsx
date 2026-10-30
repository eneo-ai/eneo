import { createFileRoute } from "@tanstack/react-router";
import { AssistantsPage } from "@/features/assistants/assistants-page";
import { spaceTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/spaces/$spaceId/assistants/")({
  head: ({ matches, match }) => spaceTitle(matches, match.context.t, match.context.t("assistants")),
  remountDeps: ({ params }) => params.spaceId,
  component: AssistantsPage
});
