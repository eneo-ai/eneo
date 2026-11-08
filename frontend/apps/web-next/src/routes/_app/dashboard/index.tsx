import { createFileRoute } from "@tanstack/react-router";
import { useTranslations } from "use-intl";
import { PageFrame } from "@/components/composites/page-frame";
import { PageHeader } from "@/components/composites/page-header";
import { DashboardList } from "@/features/dashboard/dashboard-list.client";
import { dashboardQueryOptions } from "@/features/dashboard/queries";
import { browserApi } from "@/lib/api/browser";
import { readFresh } from "@/lib/api/query";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/dashboard/")({
  loader: ({ context }) => readFresh(context.queryClient, dashboardQueryOptions(browserApi)),
  head: routeTitle("assistants"),
  component: DashboardPage
});

function DashboardPage() {
  const t = useTranslations();
  return (
    <PageFrame className="gap-6">
      <PageHeader
        title={t("assistants")}
        description={t("shell_catalog_description")}
        isDescriptionHiddenOnPhone
      />
      <DashboardList />
    </PageFrame>
  );
}
