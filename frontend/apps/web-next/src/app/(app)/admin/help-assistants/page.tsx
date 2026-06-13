import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import {
  HelpAssistantsPage,
  helpRolesQueryOptions,
  helpTemplatesQueryOptions
} from "@/features/admin/help-assistants/help-assistants-page";

export default async function AdminHelpAssistantsRoute() {
  const queryClient = getQueryClient();
  const api = eneoApi();
  await Promise.all([
    queryClient.fetchQuery(helpRolesQueryOptions(api)),
    queryClient.fetchQuery(helpTemplatesQueryOptions(api))
  ]);

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <HelpAssistantsPage />
    </HydrationBoundary>
  );
}
