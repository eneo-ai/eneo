import { createFileRoute } from "@tanstack/react-router";
import { TemplatesPage } from "@/features/admin/templates/templates-page";
import {
  appTemplatesQueryOptions,
  assistantTemplatesQueryOptions
} from "@/features/admin/templates/templates";
import { browserApi } from "@/lib/api/browser";
import { readFresh } from "@/lib/api/query";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/templates")({
  loader: async ({ context: { queryClient } }) => {
    await Promise.all([
      readFresh(queryClient, assistantTemplatesQueryOptions(browserApi)),
      readFresh(queryClient, appTemplatesQueryOptions(browserApi))
    ]);
  },
  head: routeTitle("templates"),
  component: TemplatesPage
});
