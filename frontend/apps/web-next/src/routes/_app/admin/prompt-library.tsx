import { createFileRoute } from "@tanstack/react-router";
import { PromptLibraryPage } from "@/features/admin/prompt-library/prompt-library-page";
import { promptLibraryQueryOptions } from "@/features/admin/prompt-library/prompt-library";
import { browserApi } from "@/lib/api/browser";
import { readFresh } from "@/lib/api/query";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/prompt-library")({
  loader: ({ context: { queryClient } }) =>
    readFresh(queryClient, promptLibraryQueryOptions(browserApi)),
  head: routeTitle("governance_tab_prompts"),
  component: PromptLibraryPage
});
