import { createFileRoute } from "@tanstack/react-router";
import { FlowRunPage } from "@/features/flows/runs/run-page";

export const Route = createFileRoute("/_app/spaces/$spaceId/flows/$flowId/runs/$runId")({
  remountDeps: ({ params }) => [params.spaceId, params.flowId, params.runId],
  component: RunPage
});

function RunPage() {
  const { flowId, runId } = Route.useParams();
  return <FlowRunPage flowId={flowId} runId={runId} />;
}
