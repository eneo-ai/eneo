import { createFileRoute } from "@tanstack/react-router";
import { AppDetail } from "@/features/apps/app-detail";
import { appQueryOptions, appRunsQueryOptions } from "@/features/apps/apps";
import { browserApi } from "@/lib/api/browser";
import { readFresh } from "@/lib/api/query";
import { resourceTitle } from "@/lib/route-head";
import { notFoundOn404 } from "@/lib/route-helpers";

export const Route = createFileRoute("/_app/spaces/$spaceId/apps/$appId/")({
  loader: {
    staleReloadMode: "blocking",
    handler: async ({ context, params }) => {
      const [app] = await notFoundOn404(
        Promise.all([
          readFresh(context.queryClient, appQueryOptions(browserApi, params.appId)),
          readFresh(context.queryClient, appRunsQueryOptions(browserApi, params.appId))
        ])
      );
      return { name: app.name };
    }
  },
  head: resourceTitle("apps"),
  remountDeps: ({ params }) => params.appId,
  component: AppDetailPage
});

function AppDetailPage() {
  return <AppDetail appId={Route.useParams().appId} />;
}
