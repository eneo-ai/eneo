import { createFileRoute } from "@tanstack/react-router";
import { WidgetsAdminPage } from "@/features/widget/admin/org/widgets-admin-page";
import { widgetOverviewQueryOptions } from "@/features/widget/admin/org/queries";
import {
  widgetPolicyQueryOptions,
  widgetTemplatesQueryOptions
} from "@/features/widget/admin/queries";
import { browserApi } from "@/lib/api/browser";
import { readFresh } from "@/lib/api/query";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/widgets/")({
  loader: async ({ context: { queryClient } }) => {
    await Promise.all([
      readFresh(queryClient, widgetOverviewQueryOptions(browserApi)).catch(() => undefined),
      readFresh(queryClient, widgetPolicyQueryOptions(browserApi)),
      readFresh(queryClient, widgetTemplatesQueryOptions(browserApi))
    ]);
  },
  head: routeTitle("widget_admin_nav"),
  component: WidgetsAdminPage
});
