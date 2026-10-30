import { createFileRoute } from "@tanstack/react-router";
import { appQueryOptions, appRunQueryOptions } from "@/features/apps/apps";
import { ResultDetail } from "@/features/apps/results/result-detail";
import { browserApi } from "@/lib/api/browser";
import { readFresh } from "@/lib/api/query";
import { spaceTitle } from "@/lib/route-head";
import { notFoundOn404 } from "@/lib/route-helpers";

export const Route = createFileRoute("/_app/spaces/$spaceId/apps/$appId/results/$resultId")({
  loader: {
    staleReloadMode: "blocking",
    handler: async ({ context, params }) => {
      const [app] = await notFoundOn404(
        Promise.all([
          readFresh(context.queryClient, appQueryOptions(browserApi, params.appId)),
          readFresh(context.queryClient, appRunQueryOptions(browserApi, params.resultId))
        ])
      );
      return { name: app.name, canEdit: (app.permissions ?? []).includes("edit") };
    }
  },
  head: ({ matches, match, loaderData }) =>
    spaceTitle(
      matches,
      match.context.t,
      loaderData
        ? match.context.t("space_app_result_title", { name: loaderData.name })
        : match.context.t("results")
    ),
  remountDeps: ({ params }) => params.resultId,
  component: AppResultPage
});

function AppResultPage() {
  const { spaceId, appId, resultId } = Route.useParams();
  const { canEdit } = Route.useLoaderData();
  const base = `/spaces/${spaceId}/apps/${appId}`;
  return (
    <ResultDetail
      runId={resultId}
      backHref={base}
      editHref={canEdit ? `${base}/edit` : undefined}
      newRunHref={base}
    />
  );
}
