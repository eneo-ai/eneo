import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import {
  helpRolesQueryOptions,
  helpTemplatesQueryOptions
} from "@/features/admin/help-assistants/help-assistants";
import { pageTitle } from "@/lib/page-metadata";
import { HelpAssistantsPage } from "@/features/admin/help-assistants/help-assistants-page";

export const generateMetadata = pageTitle("admin_help_assistants_nav_label");

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
