import { createFileRoute } from "@tanstack/react-router";
import { appQueryOptions, appRunsQueryOptions } from "@/features/apps/apps";
import { DashboardApp } from "@/features/dashboard/dashboard-app.client";
import { browserApi } from "@/lib/api/browser";
import { readFresh } from "@/lib/api/query";
import { resourceTitle } from "@/lib/route-head";
import { notFoundOn404 } from "@/lib/route-helpers";

export const Route = createFileRoute("/_app/dashboard/app/$appId/")({
  remountDeps: ({ params }) => params.appId,
  loader: {
    staleReloadMode: "blocking",
    handler: async ({ context, params }) => {
      const [app] = await notFoundOn404(
        Promise.all([
          readFresh(context.queryClient, appQueryOptions(browserApi, params.appId)),
          readFresh(context.queryClient, appRunsQueryOptions(browserApi, params.appId))
        ])
      );
      return app;
    }
  },
  head: resourceTitle("apps"),
  component: DashboardAppPage
});

function DashboardAppPage() {
  const { appId } = Route.useParams();
  return (
    <div className="flex flex-col p-4 sm:p-6">
      <DashboardApp appId={appId} />
    </div>
  );
}
