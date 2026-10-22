import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { notFound, unstable_rethrow } from "next/navigation";
import { EneoApiError } from "@/lib/api/errors";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { pageTitle } from "@/lib/page-metadata";
import { flowSettingsQueryOptions } from "@/features/admin/flow-settings/flow-settings";
import { FlowSettingsPage } from "@/features/admin/flow-settings/flow-settings-page";

export const generateMetadata = pageTitle("flow_admin_title");

/** The tenant's flow settings. The admin layout already admits admins only. */
export default async function AdminFlowSettingsRoute() {
  const queryClient = getQueryClient();
  try {
    await queryClient.query(flowSettingsQueryOptions(eneoApi()));
  } catch (error) {
    unstable_rethrow(error);
    // The tenant's flows gate answers 404 when flows are off. Any other
    // failure shows on the page, with a retry, instead of an error page.
    if (error instanceof EneoApiError && error.status === 404) notFound();
  }

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <FlowSettingsPage />
    </HydrationBoundary>
  );
}
