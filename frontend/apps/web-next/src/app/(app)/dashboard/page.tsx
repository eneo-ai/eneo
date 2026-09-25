import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { getTranslations } from "next-intl/server";
import { PageHeader } from "@/components/composites/page-header";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { pageTitle } from "@/lib/page-metadata";
import { DashboardList } from "./dashboard-list.client";
import { dashboardQueryOptions } from "./queries";

export const generateMetadata = pageTitle("assistants");

/** "Assistenter": every assistant and app the user can reach, grouped by space. */
export default async function DashboardPage() {
  const t = await getTranslations();

  // fetchQuery, not prefetchQuery: prefetchQuery swallows errors, which would
  // also swallow the login redirect thrown by the 401 middleware.
  const queryClient = getQueryClient();
  await queryClient.fetchQuery(dashboardQueryOptions(eneoApi()));

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 p-4 sm:p-6">
      <PageHeader title={t("assistants")} description={t("shell_catalog_description")} />
      <HydrationBoundary state={dehydrate(queryClient)}>
        <DashboardList />
      </HydrationBoundary>
    </div>
  );
}
