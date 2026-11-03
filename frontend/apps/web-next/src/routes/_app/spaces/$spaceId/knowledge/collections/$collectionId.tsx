import { createFileRoute } from "@tanstack/react-router";
import { CollectionDetail } from "@/features/knowledge/detail/collection-detail.client";
import {
  collectionBlobsQueryOptions,
  collectionQueryOptions
} from "@/features/knowledge/knowledge";
import { browserApi } from "@/lib/api/browser";
import { readFresh } from "@/lib/api/query";
import { resourceTitle } from "@/lib/route-head";
import { notFoundOn404 } from "@/lib/route-helpers";

export const Route = createFileRoute("/_app/spaces/$spaceId/knowledge/collections/$collectionId")({
  loader: {
    staleReloadMode: "blocking",
    handler: async ({ context, params }) => {
      const [collection] = await notFoundOn404(
        Promise.all([
          readFresh(context.queryClient, collectionQueryOptions(browserApi, params.collectionId)),
          readFresh(
            context.queryClient,
            collectionBlobsQueryOptions(browserApi, params.collectionId)
          )
        ])
      );
      return { name: collection.name };
    }
  },
  head: resourceTitle("collections"),
  remountDeps: ({ params }) => params.collectionId,
  component: CollectionPage
});

function CollectionPage() {
  return <CollectionDetail collectionId={Route.useParams().collectionId} />;
}
