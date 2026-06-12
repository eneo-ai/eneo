import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { getTranslations } from "next-intl/server";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { DashboardList } from "./dashboard-list.client";
import { dashboardQueryOptions } from "./queries";

export default async function DashboardPage() {
  const t = await getTranslations();

  // fetchQuery, not prefetchQuery: prefetchQuery swallows errors, which would
  // also swallow the login redirect thrown by the 401 middleware.
  const queryClient = getQueryClient();
  await queryClient.fetchQuery(dashboardQueryOptions(eneoApi()));

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold">{t("dashboard")}</h1>
      <HydrationBoundary state={dehydrate(queryClient)}>
        <DashboardList />
      </HydrationBoundary>
    </div>
  );
}
