import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Link } from "@astryxdesign/core/Link";
import { Text } from "@astryxdesign/core/Text";
import { queryOptions, useQuery, type QueryObserverResult } from "@tanstack/react-query";
import { useLocale, useTranslations } from "use-intl";
import { ClientTime } from "@/components/composites/client-time";
import { StatusLabel, type StatusTone } from "@/components/composites/status-label";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { docsUrl } from "@/lib/docs";

type TaskWorkers = Schema<"TaskWorkersStatusPublic">;

// The deployment's service names, as an operator starts them.
const EXECUTION_WORKER = "task-execution-worker";
const MAINTENANCE_WORKER = "task-maintenance-worker";

export const taskWorkersQuery = queryOptions({
  queryKey: ["admin-task-workers"],
  queryFn: () => unwrap(browserApi.GET("/api/v1/settings/task-workers")),
  // A failed check must read "could not be checked" at once; retries would keep an
  // earlier "running" on screen while they wait. Refresh is the retry.
  retry: false
});

/**
 * Whether the two task workers Flows run on are up, from their latest health
 * signal. A failed check, or a probe that could not reach the signal, always
 * reads "could not be checked" (tone `warning`), never an earlier "running":
 * a failed refetch keeps the old data, so the error is looked at first.
 */
type WorkersResult = Pick<QueryObserverResult<TaskWorkers>, "status" | "data">;

function workersState(
  result: WorkersResult,
  t: ReturnType<typeof useTranslations>
): { tone: StatusTone; label: string } {
  const data = result.data;
  if (result.status === "pending") {
    return { tone: "neutral", label: t("flows_switch_workers_checking") };
  }
  if (result.status === "error" || !data?.probe_ok) {
    return { tone: "warning", label: t("flows_switch_workers_unknown") };
  }
  const execution = data.execution_worker_ready;
  const maintenance = data.maintenance_worker_ready;
  if (execution && maintenance) {
    return { tone: "success", label: t("flows_switch_workers_running") };
  }
  return {
    tone: "error",
    label:
      !execution && !maintenance
        ? t("flows_switch_workers_not_running_both")
        : t("flows_switch_workers_not_running", {
            worker: execution ? MAINTENANCE_WORKER : EXECUTION_WORKER
          })
  };
}

/** What a screen reader hears after a check: the same words as the state line. */
export function workersAnnouncement(
  result: WorkersResult,
  t: ReturnType<typeof useTranslations>
): string {
  return t("flows_switch_workers_state", { state: workersState(result, t).label });
}

/** The workers' state beside the Flows switch: it warns, it never blocks the switch. */
export function TaskWorkersStatus() {
  const t = useTranslations();
  const locale = useLocale();
  const announce = useAnnounce();
  const query = useQuery(taskWorkersQuery);
  const state = workersState(query, t);
  const checkedAt = Math.max(query.dataUpdatedAt, query.errorUpdatedAt);
  // Not running, or not known to run: the setup guide moves up beside the state.
  const needsSetup = state.tone === "error" || state.tone === "warning";
  const guide = (
    <Link
      href={docsUrl("guides/flows/integrating-flows", locale, "switch-flows-on")}
      isExternalLink
      hasUnderline
      newTabLabel={t("chat_opens_in_new_tab")}
      className="pointer-coarse:min-h-11"
    >
      {needsSetup ? t("flows_switch_guide_workers") : t("flows_switch_guide")}
    </Link>
  );

  return (
    <div className="mt-3 flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <StatusLabel
          status={state.tone}
          label={t("flows_switch_workers_state", { state: state.label })}
        />
        {checkedAt > 0 ? (
          <Text type="supporting">
            {t.rich(
              state.tone === "warning"
                ? "flows_switch_workers_attempted_at"
                : "flows_switch_workers_checked_at",
              {
                time: () => (
                  <ClientTime value={new Date(checkedAt).toISOString()} format="relative" />
                )
              }
            )}
          </Text>
        ) : null}
        <Button
          size="sm"
          label={t("flows_switch_workers_refresh")}
          // Stays focusable while checking; a second press is ignored.
          isLoading={query.isFetching}
          isInterruptible
          onClick={() => {
            if (query.isFetching) return;
            void query.refetch().then((result) => announce(workersAnnouncement(result, t)));
          }}
        >
          {t("refresh")}
        </Button>
        {needsSetup ? guide : null}
      </div>
      <Text type="supporting">
        {t("flows_switch_workers_basis")} {needsSetup ? null : guide}
      </Text>
    </div>
  );
}
