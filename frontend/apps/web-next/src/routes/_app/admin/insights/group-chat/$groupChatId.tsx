import { createFileRoute } from "@tanstack/react-router";
import { validateInsightViewSearch } from "@/features/admin/insights/assistant-insights-view";
import { GroupChatInsightsPage } from "@/features/admin/insights/assistant-insights-page";
import { groupChatQueryOptions } from "@/features/group-chats/use-group-chat";
import { browserApi } from "@/lib/api/browser";
import { readFresh } from "@/lib/api/query";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/insights/group-chat/$groupChatId")({
  validateSearch: validateInsightViewSearch,
  loader: ({ context: { queryClient }, params }) =>
    readFresh(queryClient, groupChatQueryOptions(browserApi, params.groupChatId)),
  remountDeps: ({ params }) => params.groupChatId,
  head: routeTitle("insights"),
  component: GroupChatInsightsRoute
});

function GroupChatInsightsRoute() {
  const { groupChatId } = Route.useParams();
  return <GroupChatInsightsPage groupChatId={groupChatId} />;
}
