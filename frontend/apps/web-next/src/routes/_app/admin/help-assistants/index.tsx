import { createFileRoute } from "@tanstack/react-router";
import { helperChatPolicyQueryOptions } from "@/features/admin/helper-chat/helper-chat-policy";
import { HelperChatSettingsPage } from "@/features/admin/helper-chat/helper-chat-settings-page";
import { adminModelsQueryOptions } from "@/features/admin/models/models";
import { browserApi } from "@/lib/api/browser";
import { readFresh, warmQuery } from "@/lib/api/query";
import { routeTitle } from "@/lib/route-head";

/** The helper assistant's organisation settings (the old help assistants' address). */
export const Route = createFileRoute("/_app/admin/help-assistants/")({
  loader: async ({ context: { queryClient } }) => {
    warmQuery(queryClient, adminModelsQueryOptions(browserApi));
    try {
      await readFresh(queryClient, helperChatPolicyQueryOptions(browserApi));
    } catch {
      // A failed read stays with the page's QueryStateBoundary, which can retry.
    }
  },
  head: routeTitle("admin_helper_title"),
  component: HelperChatSettingsPage
});
