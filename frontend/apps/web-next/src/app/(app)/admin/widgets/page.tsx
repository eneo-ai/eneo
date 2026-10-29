import { dehydrate, HydrationBoundary, noop } from "@tanstack/react-query";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { pageTitle } from "@/lib/page-metadata";
import { widgetOverviewQueryOptions } from "@/features/widget/admin/org/queries";
import { WidgetsAdminPage } from "@/features/widget/admin/org/widgets-admin-page";
import {
  widgetPolicyQueryOptions,
  widgetTemplatesQueryOptions
} from "@/features/widget/admin/queries";

export const generateMetadata = pageTitle("widget_admin_nav");

export default async function AdminWidgetsRoute() {
  const queryClient = getQueryClient();
  const api = eneoApi();
  // A failing overview is reported on the page rather than failing the route.
  await Promise.all([
    queryClient.query(widgetOverviewQueryOptions(api)).catch(noop),
    queryClient.query(widgetPolicyQueryOptions(api)),
    queryClient.query(widgetTemplatesQueryOptions(api))
  ]);

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <WidgetsAdminPage />
    </HydrationBoundary>
  );
}
