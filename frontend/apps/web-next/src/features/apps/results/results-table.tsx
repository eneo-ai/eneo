"use client";

import { useJobEventsConnected } from "@/features/jobs/job-events";
import { useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { FileText, MoreHorizontal, Paperclip, Trash2 } from "lucide-react";
import Link from "@/lib/link";
import { useTranslations } from "use-intl";
import { useMemo, useRef, useState } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { EmptyState } from "@/components/composites/empty-state";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Table } from "@/components/astryx/table";
import {
  pixel,
  proportional,
  useTableSortable,
  useTableSortableState,
  type TableColumn,
  type TableSortComparator
} from "@astryxdesign/core/Table";
import { useCollator } from "@astryxdesign/core/i18n";
import { ResourceFilterInput } from "@/features/spaces/resource-filter-input";
import { RemovalFocusScope, useRemovalMutation } from "@/features/spaces/removal";
import { matchesSearch } from "@/lib/search";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { pollWhile } from "@/lib/api/query";
import { ClientTime, useClientTimeText } from "@/components/composites/client-time";
import { appRunsQueryOptions, getResultTitle, isRunActive, type AppRunSparse } from "../apps";
import { AppRunStatusToken, appRunStatusLabel } from "../status-token";

const RESULTS_POLL_MS = 5_000;

function resultTitleLabels(t: (key: string) => string) {
  return { inputPrefix: t("input"), empty: t("app_run_no_input_title") };
}

function ResultActions({ appId, run }: { appId: string; run: AppRunSparse }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [showDelete, setShowDelete] = useState(false);
  const menuRef = useRef<HTMLButtonElement>(null);
  const titleLabels = resultTitleLabels(t);
  // A run has no name of its own; its row shows when it was made, so the
  // menu is named by that time in the viewer's time zone.
  const time = useClientTimeText(run.created_at, "date_time");

  const deleteRun = useRemovalMutation({
    anchor: menuRef,
    mutationFn: () =>
      unwrap(browserApi.DELETE("/api/v1/app-runs/{id}/", { params: { path: { id: run.id } } })),
    refresh: () => queryClient.invalidateQueries({ queryKey: ["apps", appId, "runs"] }),
    onRemoved: () => setShowDelete(false)
  });

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            ref={menuRef}
            variant="ghost"
            size="icon"
            aria-label={time ? t("ui_more_actions_for", { name: time }) : t("actions")}
          >
            <MoreHorizontal className="size-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem variant="destructive" onSelect={() => setShowDelete(true)}>
            <Trash2 className="size-4" /> {t("delete")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <ConfirmDialogControlled
        open={showDelete}
        onOpenChange={setShowDelete}
        title={t("delete_result")}
        description={t("confirm_delete_result", { resultTitle: getResultTitle(run, titleLabels) })}
        confirmLabel={deleteRun.isPending ? t("deleting") : t("delete")}
        pending={deleteRun.isPending}
        onConfirm={() => deleteRun.mutate()}
      />
    </>
  );
}

function ResultInputCell({ run }: { run: AppRunSparse }) {
  const t = useTranslations();
  const { text, files } = run.input;
  if (!text && files.length === 0) {
    return (
      <span className="text-muted-foreground">{t("this_run_did_not_receive_any_inputs")}</span>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      {text && (
        <span className="flex max-w-[40ch] items-center gap-1.5">
          <FileText className="text-muted-foreground size-4 shrink-0" />
          <span className="truncate">
            {t("input")}: {text}
          </span>
        </span>
      )}
      {files.map((file) => (
        <span key={file.id} className="flex max-w-[30ch] items-center gap-1.5">
          <Paperclip className="text-muted-foreground size-4 shrink-0" />
          <span className="truncate">{file.name}</span>
        </span>
      ))}
    </div>
  );
}

/** Run history for an app; polls while any run is still in progress. */
export function ResultsTable({
  appId,
  resultHref
}: {
  appId: string;
  resultHref: (runId: string) => string;
}) {
  const t = useTranslations();
  // A finished run arrives through the job feed (every run is a job), which
  // refreshes this list; polling only covers the time the feed is down.
  const live = useJobEventsConnected();
  const { data: runs } = useSuspenseQuery({
    ...appRunsQueryOptions(browserApi, appId),
    refetchInterval: pollWhile(
      (runs) => !live && !!runs?.some((run) => isRunActive(run.status)),
      RESULTS_POLL_MS
    )
  });

  const collator = useCollator();
  const [filter, setFilter] = useState("");
  const listRef = useRef<HTMLDivElement>(null);
  const labels = useMemo(() => resultTitleLabels(t), [t]);
  const matched = useMemo(
    () => runs.filter((run) => matchesSearch([getResultTitle(run, labels)], filter)),
    [runs, filter, labels]
  );
  const comparators = useMemo<
    Record<"name" | "status" | "created_at", TableSortComparator<AppRunSparse>>
  >(
    () => ({
      name: (a, b) => collator.compare(getResultTitle(a, labels), getResultTitle(b, labels)),
      status: (a, b) =>
        collator.compare(appRunStatusLabel(a.status, t), appRunStatusLabel(b.status, t)),
      created_at: (a, b) =>
        new Date(a.created_at ?? 0).getTime() - new Date(b.created_at ?? 0).getTime()
    }),
    [collator, labels, t]
  );
  const { sortedData, sortConfig } = useTableSortableState<
    AppRunSparse,
    "name" | "status" | "created_at"
  >({
    data: matched,
    comparators,
    defaultSort: [{ sortKey: "created_at", direction: "descending" }],
    allowUnsortedState: false
  });
  const sort = useTableSortable<AppRunSparse, "name" | "status" | "created_at">(sortConfig);
  const columns: TableColumn<AppRunSparse>[] = [
    {
      key: "name",
      header: t("name"),
      width: proportional(2),
      sortable: true,
      renderCell: (run) => (
        <Link href={resultHref(run.id)} className="hover:underline">
          <ResultInputCell run={run} />
        </Link>
      )
    },
    {
      key: "status",
      header: t("status"),
      width: proportional(1),
      sortable: true,
      renderCell: (run) => <AppRunStatusToken status={run.status} />
    },
    {
      key: "created_at",
      header: t("created"),
      width: proportional(1),
      sortable: true,
      renderCell: (run) =>
        run.created_at ? <ClientTime value={run.created_at} format="date_time" /> : "—"
    },
    {
      key: "actions",
      header: t("actions"),
      width: pixel(64),
      renderCell: (run) => <ResultActions appId={appId} run={run} />
    }
  ];
  return (
    <RemovalFocusScope target={listRef}>
      <div
        ref={listRef}
        tabIndex={-1}
        role="group"
        aria-label={t("results")}
        className="focus-visible:outline-ring flex min-w-0 flex-col gap-4 focus-visible:outline-2 focus-visible:outline-offset-4"
      >
        {runs.length === 0 ? (
          <EmptyState title={t("no_previous_results_found")} />
        ) : (
          <>
            <ResourceFilterInput
              value={filter}
              onChange={setFilter}
              label={t("resource_filter_results")}
              placeholder={t("ui_filter_items", { resourceName: t("resource_results") })}
              resultCount={matched.length}
            />
            {matched.length === 0 ? (
              <EmptyState title={t("no_results_found")} isCompact />
            ) : (
              <Table
                data={sortedData}
                columns={columns}
                idKey="id"
                aria-label={t("results")}
                plugins={{ sort }}
              />
            )}
          </>
        )}
      </div>
    </RemovalFocusScope>
  );
}
