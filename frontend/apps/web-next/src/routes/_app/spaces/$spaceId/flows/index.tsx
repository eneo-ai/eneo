import { createFileRoute } from "@tanstack/react-router";
import { FlowsPage } from "@/features/flows/flows-page";
import { flowsListQueryOptions } from "@/features/flows/flows-api";
import { spaceQueryOptions } from "@/features/spaces/space";
import { browserApi } from "@/lib/api/browser";
import { readCached, readFresh } from "@/lib/api/query";
import { spaceTitle } from "@/lib/route-head";
import { notFoundOn404 } from "@/lib/route-helpers";

export const Route = createFileRoute("/_app/spaces/$spaceId/flows/")({
  loader: {
    staleReloadMode: "blocking",
    handler: async ({ context, params }) => {
      const space = await readCached(
        context.queryClient,
        spaceQueryOptions(browserApi, params.spaceId)
      );
      await notFoundOn404(
        readFresh(context.queryClient, flowsListQueryOptions(browserApi, space.id))
      );
    }
  },
  head: ({ matches, match }) => spaceTitle(matches, match.context.t, match.context.t("flows")),
  remountDeps: ({ params }) => params.spaceId,
  component: FlowsPage
});
