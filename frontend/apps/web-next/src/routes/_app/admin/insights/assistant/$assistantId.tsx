import { createFileRoute } from "@tanstack/react-router";
import { validateAssistantInsightSearch } from "@/features/admin/insights/assistant-insights-view";
import { AssistantInsightsPage } from "@/features/admin/insights/assistant-insights-page";
import { assistantQueryOptions } from "@/features/assistants/editor/use-assistant";
import { browserApi } from "@/lib/api/browser";
import { readFresh } from "@/lib/api/query";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/insights/assistant/$assistantId")({
  validateSearch: validateAssistantInsightSearch,
  loader: ({ context: { queryClient }, params }) =>
    readFresh(queryClient, assistantQueryOptions(browserApi, params.assistantId)),
  remountDeps: ({ params }) => params.assistantId,
  head: routeTitle("insights"),
  component: AssistantInsightsRoute
});

function AssistantInsightsRoute() {
  const { assistantId } = Route.useParams();
  return <AssistantInsightsPage assistantId={assistantId} />;
}
