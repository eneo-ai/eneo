import { createFileRoute, notFound, redirect } from "@tanstack/react-router";
import { ItemDetail } from "@/features/knowledge/integrations/item-detail.client";
import { sourceHref, sourceTabParam } from "@/features/knowledge/integrations/sources";
import { spaceQueryOptions } from "@/features/spaces/space";
import { browserApi } from "@/lib/api/browser";
import { readFresh } from "@/lib/api/query";
import { resourceTitle } from "@/lib/route-head";
import { notFoundOn404 } from "@/lib/route-helpers";
import { parseSearch } from "@/lib/router/search";

export const Route = createFileRoute(
  "/_app/spaces/$spaceId/knowledge/integrations/$integrationKnowledgeId"
)({
  loader: {
    staleReloadMode: "blocking",
    handler: async ({ context, params, location }) => {
      const space = await notFoundOn404(
        readFresh(context.queryClient, spaceQueryOptions(browserApi, params.spaceId))
      );
      const item = space.knowledge.integration_knowledge_list.items.find(
        (entry) => entry.id === params.integrationKnowledgeId && entry.space_id === space.id
      );
      if (!item) throw notFound();
      if (item.wrapper_id && item.integration_type === "sharepoint") {
        throw redirect({
          href: sourceHref(
            params.spaceId,
            { kind: "wrapper", id: item.wrapper_id },
            {
              folder: item.id,
              tab: sourceTabParam(parseSearch(location.searchStr).tab)
            }
          )
        });
      }
      return { name: item.name, items: [item] };
    }
  },
  head: resourceTitle("integrations"),
  remountDeps: ({ params }) => [params.spaceId, params.integrationKnowledgeId],
  component: IntegrationItemPage
});

function IntegrationItemPage() {
  const { integrationKnowledgeId } = Route.useParams();
  const { items } = Route.useLoaderData();
  return <ItemDetail itemId={integrationKnowledgeId} loaded={{ items }} />;
}
