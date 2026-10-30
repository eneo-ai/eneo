import { createFileRoute, notFound, Outlet } from "@tanstack/react-router";
import { flowQueryOptions } from "@/features/flows/flows-api";
import { spaceQueryOptions } from "@/features/spaces/space";
import { browserApi } from "@/lib/api/browser";
import { readCached, readFresh } from "@/lib/api/query";
import { resourceTitle } from "@/lib/route-head";
import { notFoundOn404 } from "@/lib/route-helpers";

export const Route = createFileRoute("/_app/spaces/$spaceId/flows/$flowId")({
  loader: {
    staleReloadMode: "blocking",
    handler: async ({ context, params }) => {
      const [space, flow] = await notFoundOn404(
        Promise.all([
          readCached(context.queryClient, spaceQueryOptions(browserApi, params.spaceId)),
          readFresh(context.queryClient, flowQueryOptions(browserApi, params.flowId))
        ])
      );
      if (flow.space_id !== space.id) throw notFound();
      return { name: flow.name };
    }
  },
  head: resourceTitle("flows"),
  component: Outlet
});
