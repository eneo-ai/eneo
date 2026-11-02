import { useAnnounce } from "@astryxdesign/core/hooks";
import { useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { browserApi } from "@/lib/api/browser";
import { useRouter } from "@/lib/navigation";
import { useSpace } from "@/features/spaces/use-space";
import { flowQueryOptions } from "./flows-api";
import { runKeys } from "./runs/runs-api";
import { runHref } from "./runs/runs-list";
import { rememberStartedRun } from "./runs/runs-optimistic";
import { StartRunDialog } from "./runs/start-run-dialog";

/**
 * The form that starts a run of a flow, and what follows a start. It belongs
 * to the flow's page, above the lean phone page and the workspace, not to
 * either: a tablet split down to a phone's width swaps one for the other, and the
 * form (a recording in it, files uploaded) must outlive the swap.
 */
export function FlowRunStarter({
  flowId,
  open,
  onOpenChange
}: {
  flowId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { routeId } = useSpace();
  const { data: flow } = useSuspenseQuery(flowQueryOptions(browserApi, flowId));
  if (flow.published_version == null || !flow.permissions.can_run) return null;

  return (
    <StartRunDialog
      flow={flow}
      open={open}
      onOpenChange={onOpenChange}
      onStarted={(run) => {
        onOpenChange(false);
        // The runs list shows the run at once, before it is read again.
        rememberStartedRun(queryClient, flow.id, run);
        void queryClient.invalidateQueries({ queryKey: runKeys.list(flow.id) });
        announce(t("flow_runs_started"));
        // The run's own page follows it while it moves.
        router.push(runHref(routeId, flow.id, run.id));
      }}
    />
  );
}
