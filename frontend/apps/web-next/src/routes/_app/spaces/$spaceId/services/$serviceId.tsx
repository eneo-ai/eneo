import { createFileRoute } from "@tanstack/react-router";
import { ServiceDetail } from "@/features/services/service-detail";
import { serviceQueryOptions } from "@/features/services/services";
import { browserApi } from "@/lib/api/browser";
import { readFresh } from "@/lib/api/query";
import { resourceTitle } from "@/lib/route-head";
import { notFoundOn404 } from "@/lib/route-helpers";

export const Route = createFileRoute("/_app/spaces/$spaceId/services/$serviceId")({
  loader: {
    staleReloadMode: "blocking",
    handler: async ({ context, params }) => {
      const { name } = await notFoundOn404(
        readFresh(context.queryClient, serviceQueryOptions(browserApi, params.serviceId))
      );
      return { name };
    }
  },
  head: resourceTitle("services"),
  remountDeps: ({ params }) => params.serviceId,
  component: ServiceDetailPage
});

function ServiceDetailPage() {
  return <ServiceDetail serviceId={Route.useParams().serviceId} />;
}
