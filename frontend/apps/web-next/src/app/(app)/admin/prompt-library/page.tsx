import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import {
  promptLibraryQueryOptions,
  PromptLibraryPage
} from "@/features/admin/prompt-library/prompt-library-page";

export default async function AdminPromptLibraryRoute() {
  const queryClient = getQueryClient();
  await queryClient.fetchQuery(promptLibraryQueryOptions(eneoApi()));

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <PromptLibraryPage />
    </HydrationBoundary>
  );
}
