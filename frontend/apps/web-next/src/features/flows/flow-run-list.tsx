"use client";

import { Button } from "@astryxdesign/core/Button";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { ClientTime } from "@/components/composites/client-time";
import { EmptyState } from "@/components/composites/empty-state";
import { ListError, QueryStateBoundary } from "@/components/composites/query-state";
import { StatusLabel } from "@/components/composites/status-label";
import { cn } from "@/lib/utils";
import { runDisplayName, runStatusLabel, runStatusTone } from "./flow-labels";
import { flowRunsQueryOptions, isActiveRun } from "./flows";

const ROW_CLASS =
  "focus-visible:outline-ring hover:bg-ax-hover flex min-h-11 w-full items-center gap-3 rounded-ax-inner px-2 py-1.5 text-start text-[13px] focus-visible:outline-2 focus-visible:-outline-offset-2";

/** The runs of a flow, newest first; a row opens the run. */
export function FlowRunList({
  flowId,
  selectedRunId,
  onSelect
}: {
  flowId: string;
  selectedRunId: string | null;
  onSelect: (runId: string) => void;
}) {
  const t = useTranslations();
  const runs = useInfiniteQuery({
    ...flowRunsQueryOptions(flowId),
    // A list with a run still going refreshes with the run's own polling rhythm.
    refetchInterval: (query) =>
      query.state.data?.pages.some((page) => page.items.some((run) => isActiveRun(run.status)))
        ? 5000
        : false
  });
  const items = runs.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <QueryStateBoundary query={runs} rows={3}>
      {() =>
        items.length === 0 ? (
          <EmptyState
            isCompact
            framed={false}
            headingLevel={3}
            title={t("flow_runs_empty_title")}
            description={t("flow_runs_empty_description")}
          />
        ) : (
          <div className="flex flex-col gap-2">
            <ul aria-label={t("flow_runs_list_label")} className="m-0 flex list-none flex-col p-0">
              {items.map((run) => {
                const current = run.id === selectedRunId;
                return (
                  <li key={run.id}>
                    <button
                      type="button"
                      aria-current={current ? "true" : undefined}
                      onClick={() => onSelect(run.id)}
                      className={cn(
                        ROW_CLASS,
                        current && "bg-ax-accent-muted hover:bg-ax-accent-muted"
                      )}
                    >
                      <span className="min-w-0 flex-1 truncate font-medium">
                        {runDisplayName(run)}
                        <span className="text-ax-text-secondary ms-2 text-xs font-normal">
                          <ClientTime value={run.created_at} format="auto" />
                          {" · "}
                          {t("flow_run_version", { version: run.flow_version })}
                        </span>
                      </span>
                      <StatusLabel
                        status={runStatusTone(run.status)}
                        label={runStatusLabel(run.status, t)}
                        isPulsing={run.status === "running"}
                        className="shrink-0 text-xs"
                      />
                    </button>
                  </li>
                );
              })}
            </ul>
            {runs.hasNextPage && (
              <Button
                label={runs.isFetchingNextPage ? t("loading") : t("load_more")}
                size="sm"
                className="self-center"
                isLoading={runs.isFetchingNextPage}
                isInterruptible
                onClick={() => {
                  if (!runs.isFetchingNextPage) void runs.fetchNextPage();
                }}
              />
            )}
            {runs.isFetchNextPageError && (
              <ListError error={runs.error} onRetry={() => void runs.fetchNextPage()} />
            )}
          </div>
        )
      }
    </QueryStateBoundary>
  );
}
