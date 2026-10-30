import { createFileRoute } from "@tanstack/react-router";
import { appQueryOptions, appRunQueryOptions } from "@/features/apps/apps";
import { ResultDetail } from "@/features/apps/results/result-detail";
import { browserApi } from "@/lib/api/browser";
import { readFresh } from "@/lib/api/query";
import { title } from "@/lib/route-head";
import { notFoundOn404 } from "@/lib/route-helpers";

export const Route = createFileRoute("/_app/dashboard/app/$appId/results/$resultId")({
  loader: {
    staleReloadMode: "blocking",
    handler: async ({ context, params }) => {
      const [app] = await notFoundOn404(
        Promise.all([
          readFresh(context.queryClient, appQueryOptions(browserApi, params.appId)),
          readFresh(context.queryClient, appRunQueryOptions(browserApi, params.resultId))
        ])
      );
      return app;
    }
  },
  head: ({ match, loaderData }) =>
    title(
      loaderData
        ? match.context.t("space_app_result_title", { name: loaderData.name })
        : match.context.t("results")
    ),
  component: DashboardResultPage
});

function DashboardResultPage() {
  const { appId, resultId } = Route.useParams();
  const base = `/dashboard/app/${appId}`;
  return (
    <div className="flex flex-col p-4 sm:p-6">
      <ResultDetail runId={resultId} backHref={base} newRunHref={base} />
    </div>
  );
}
