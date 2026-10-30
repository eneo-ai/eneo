import { createFileRoute } from "@tanstack/react-router";
import { AppEditor } from "@/features/apps/editor/app-editor";
import { appQueryOptions } from "@/features/apps/apps";
import { browserApi } from "@/lib/api/browser";
import { readFresh } from "@/lib/api/query";
import { spaceTitle } from "@/lib/route-head";
import { notFoundOn404 } from "@/lib/route-helpers";

export const Route = createFileRoute("/_app/spaces/$spaceId/apps/$appId/edit")({
  loader: {
    staleReloadMode: "blocking",
    handler: async ({ context, params }) => {
      const { name } = await notFoundOn404(
        readFresh(context.queryClient, appQueryOptions(browserApi, params.appId))
      );
      return { name };
    }
  },
  head: ({ matches, match, loaderData }) =>
    spaceTitle(
      matches,
      match.context.t,
      loaderData
        ? match.context.t("space_edit_title", { name: loaderData.name })
        : match.context.t("apps")
    ),
  remountDeps: ({ params }) => params.appId,
  component: AppEditPage
});

function AppEditPage() {
  return <AppEditor appId={Route.useParams().appId} />;
}
