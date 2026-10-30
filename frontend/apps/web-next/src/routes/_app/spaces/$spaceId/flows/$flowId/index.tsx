import { createFileRoute } from "@tanstack/react-router";
import { FlowPage } from "@/features/flows/flow-page";
import { parseFlowSearch } from "@/features/flows/flow-search";

export const Route = createFileRoute("/_app/spaces/$spaceId/flows/$flowId/")({
  validateSearch: parseFlowSearch,
  remountDeps: ({ params }) => [params.spaceId, params.flowId],
  component: FlowDetailPage
});

function FlowDetailPage() {
  return <FlowPage flowId={Route.useParams().flowId} />;
}
