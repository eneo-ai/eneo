import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { pageTitle } from "@/lib/page-metadata";
import { assistantQueryOptions } from "@/features/assistants/editor/use-assistant";
import { AssistantInsightsPage } from "@/features/admin/insights/assistant-insights-page";

export const generateMetadata = pageTitle("insights");

export default async function AdminAssistantInsightsRoute({
  params
}: {
  params: Promise<{ assistantId: string }>;
}) {
  const { assistantId } = await params;
  const queryClient = getQueryClient();
  await queryClient.fetchQuery(assistantQueryOptions(eneoApi(), assistantId));

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <AssistantInsightsPage assistantId={assistantId} />
    </HydrationBoundary>
  );
}
