import { createFileRoute } from "@tanstack/react-router";
import { HelpAssistantsPage } from "@/features/admin/help-assistants/help-assistants-page";
import {
  helpRolesQueryOptions,
  helpTemplatesQueryOptions
} from "@/features/admin/help-assistants/help-assistants";
import { browserApi } from "@/lib/api/browser";
import { readFresh } from "@/lib/api/query";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/help-assistants/")({
  loader: async ({ context: { queryClient } }) => {
    await Promise.all([
      readFresh(queryClient, helpRolesQueryOptions(browserApi)),
      readFresh(queryClient, helpTemplatesQueryOptions(browserApi))
    ]);
  },
  head: routeTitle("admin_help_assistants_nav_label"),
  component: HelpAssistantsPage
});
