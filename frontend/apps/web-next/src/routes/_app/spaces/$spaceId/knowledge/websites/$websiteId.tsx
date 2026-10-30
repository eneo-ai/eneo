import { createFileRoute } from "@tanstack/react-router";
import { WebsiteDetail } from "@/features/knowledge/detail/website-detail.client";
import {
  formatWebsiteName,
  websiteBlobPagesQueryOptions,
  websiteCrawlRunsQueryOptions,
  websiteLatestRunQueryOptions,
  websiteQueryOptions
} from "@/features/knowledge/knowledge";
import { browserApi } from "@/lib/api/browser";
import { readFresh } from "@/lib/api/query";
import { resourceTitle } from "@/lib/route-head";
import { notFoundOn404 } from "@/lib/route-helpers";
import { runtimeConfig } from "@/lib/runtime-config";

export const Route = createFileRoute("/_app/spaces/$spaceId/knowledge/websites/$websiteId")({
  loader: {
    staleReloadMode: "blocking",
    handler: async ({ context, params }) => {
      const [website] = await notFoundOn404(
        Promise.all([
          readFresh(context.queryClient, websiteQueryOptions(browserApi, params.websiteId)),
          readFresh(
            context.queryClient,
            websiteLatestRunQueryOptions(browserApi, params.websiteId)
          ),
          context.queryClient.infiniteQuery(
            websiteCrawlRunsQueryOptions(browserApi, params.websiteId)
          ),
          context.queryClient.infiniteQuery(
            websiteBlobPagesQueryOptions(browserApi, params.websiteId)
          )
        ])
      );
      return { name: formatWebsiteName(website) };
    }
  },
  head: resourceTitle("websites"),
  remountDeps: ({ params }) => params.websiteId,
  component: WebsitePage
});

function WebsitePage() {
  return (
    <WebsiteDetail
      websiteId={Route.useParams().websiteId}
      integrationRequestFormUrl={runtimeConfig().request_integration_form_url ?? undefined}
    />
  );
}
