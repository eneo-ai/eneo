import { createFileRoute, notFound } from "@tanstack/react-router";
import { WrapperDetail } from "@/features/knowledge/integrations/wrapper-detail.client";
import { findWrapperSource } from "@/features/knowledge/integrations/sources";
import { spaceQueryOptions } from "@/features/spaces/space";
import { browserApi } from "@/lib/api/browser";
import { readFresh } from "@/lib/api/query";
import { resourceTitle } from "@/lib/route-head";
import { notFoundOn404 } from "@/lib/route-helpers";

export const Route = createFileRoute(
  "/_app/spaces/$spaceId/knowledge/integrations/wrapper/$wrapperId"
)({
  loader: {
    staleReloadMode: "blocking",
    handler: async ({ context, params }) => {
      const space = await notFoundOn404(
        readFresh(context.queryClient, spaceQueryOptions(browserApi, params.spaceId))
      );
      const source = findWrapperSource(
        space.knowledge.integration_knowledge_list.items.filter(
          (item) => item.space_id === space.id
        ),
        params.wrapperId
      );
      if (!source) throw notFound();
      return { name: source.name, items: source.items };
    }
  },
  head: resourceTitle("integrations"),
  remountDeps: ({ params }) => [params.spaceId, params.wrapperId],
  component: IntegrationWrapperPage
});

function IntegrationWrapperPage() {
  const { wrapperId } = Route.useParams();
  const { items } = Route.useLoaderData();
  return <WrapperDetail wrapperId={wrapperId} loaded={{ items }} />;
}
