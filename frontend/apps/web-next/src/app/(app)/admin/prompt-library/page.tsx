import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { pageTitle } from "@/lib/page-metadata";
import { promptLibraryQueryOptions } from "@/features/admin/prompt-library/prompt-library";
import { PromptLibraryPage } from "@/features/admin/prompt-library/prompt-library-page";

export const generateMetadata = pageTitle("governance_tab_prompts");

export default async function AdminPromptLibraryRoute() {
  const queryClient = getQueryClient();
  await queryClient.fetchQuery(promptLibraryQueryOptions(eneoApi()));

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <PromptLibraryPage />
    </HydrationBoundary>
  );
}
