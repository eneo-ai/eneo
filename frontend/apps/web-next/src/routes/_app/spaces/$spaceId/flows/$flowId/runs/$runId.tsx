import { createFileRoute } from "@tanstack/react-router";
import { FlowRunPage } from "@/features/flows/runs/run-page";
import type { RouterContext } from "@/router";
import { spaceTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/spaces/$spaceId/flows/$flowId/runs/$runId")({
  remountDeps: ({ params }) => [params.spaceId, params.flowId, params.runId],
  // "Körning · <flow> · <space> · Eneo": a run is not titled as its flow.
  head: ({
    match,
    matches
  }: {
    match: { context: Pick<RouterContext, "t"> };
    matches: readonly { routeId: string; loaderData?: unknown }[];
  }) => {
    const t = match.context.t;
    const flow = matches.find((m) => m.routeId === "/_app/spaces/$spaceId/flows/$flowId")
      ?.loaderData as { name: string } | undefined;
    return spaceTitle(
      matches,
      t,
      [t("flow_runs_run_title_plain"), flow?.name].filter(Boolean).join(" · ")
    );
  },
  component: RunPage
});

function RunPage() {
  const { flowId, runId } = Route.useParams();
  return <FlowRunPage flowId={flowId} runId={runId} />;
}
