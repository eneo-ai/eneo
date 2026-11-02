import { List, ListItem } from "@astryxdesign/core/List";
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
import { useRemovalMutation } from "@/features/spaces/removal";
import { matchesSearch } from "@/lib/search";
import { useFocusRescue } from "@/lib/focus-rescue";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { pollWhile } from "@/lib/api/query";
import { ClientTime, useClientTimeText } from "@/components/composites/client-time";
import { useFocusAcrossLayouts } from "@/lib/hooks/use-focus-across-layouts";
import { PHONE_QUERY, useMediaMatch } from "@/lib/hooks/use-media-match";
import { appRunsQueryOptions, getResultTitle, isRunActive, type AppRunSparse } from "../apps";
import { AppRunStatusToken, appRunStatusLabel } from "../status-token";

const RESULTS_POLL_MS = 5_000;

function resultTitleLabels(t: (key: string) => string) {
  return { inputPrefix: t("input"), empty: t("this_run_did_not_receive_any_inputs") };
}

function ResultActions({
  run,
  onDelete
}: {
  run: AppRunSparse;
  onDelete: (run: AppRunSparse, anchor: HTMLButtonElement | null) => void;
}) {
  const t = useTranslations();
  const menuRef = useRef<HTMLButtonElement>(null);
  // A run has no name of its own; its row shows when it was made, so the
  // menu is named by that time in the viewer's time zone.
  const time = useClientTimeText(run.created_at, "date_time");

  return (
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
        <DropdownMenuItem variant="destructive" onSelect={() => onDelete(run, menuRef.current)}>
          <Trash2 className="size-4" /> {t("delete")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** `wrap`: a phone row shows the whole input, wrapped; the table cuts it at 40 characters. */
function ResultInputCell({ run, wrap = false }: { run: AppRunSparse; wrap?: boolean }) {
  const t = useTranslations();
  const labels = resultTitleLabels(t);
  const { text, files } = run.input;
  if (!text && files.length === 0) {
    return <span className="text-muted-foreground">{getResultTitle(run, labels)}</span>;
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      {text && (
        <span
          className={wrap ? "flex items-start gap-1.5" : "flex max-w-[40ch] items-center gap-1.5"}
        >
          <FileText className="text-muted-foreground size-4 shrink-0" />
          <span className={wrap ? "break-words" : "truncate"}>
            {labels.inputPrefix}: {text}
          </span>
        </span>
      )}
      {files.map((file) => (
        <span
          key={file.id}
          className={wrap ? "flex items-start gap-1.5" : "flex max-w-[30ch] items-center gap-1.5"}
        >
          <Paperclip className="text-muted-foreground size-4 shrink-0" />
          <span className={wrap ? "break-words" : "truncate"}>{file.name}</span>
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
  const phone = useMediaMatch(PHONE_QUERY);
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
  const menuAnchor = useRef<HTMLButtonElement | null>(null);
  const [runToDelete, setRunToDelete] = useState<AppRunSparse | null>(null);
  const queryClient = useQueryClient();
  const rescueFocus = useFocusRescue();
  // The list owns deletion so replacing rows with a table cannot close its dialog or reset a request.
  const deleteRun = useRemovalMutation({
    anchor: menuAnchor,
    focusTarget: listRef,
    mutationFn: (run: AppRunSparse) =>
      unwrap(browserApi.DELETE("/api/v1/app-runs/{id}/", { params: { path: { id: run.id } } })),
    refresh: () => queryClient.invalidateQueries({ queryKey: ["apps", appId, "runs"] }),
    onRemoved: () => setRunToDelete(null)
  });
  function requestDelete(run: AppRunSparse, anchor: HTMLButtonElement | null) {
    menuAnchor.current = anchor;
    setRunToDelete(run);
  }
  useFocusAcrossLayouts(listRef, phone);
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
      renderCell: (run) => <ResultActions run={run} onDelete={requestDelete} />
    }
  ];
  return (
    <>
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
            ) : phone ? (
              <List hasDividers edgeCompensation="inline" aria-label={t("results")}>
                {sortedData.map((run) => (
                  <ListItem
                    key={run.id}
                    href={resultHref(run.id)}
                    label={<ResultInputCell run={run} wrap />}
                    description={
                      <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                        <AppRunStatusToken status={run.status} />
                        <span className="tabular-nums">
                          {run.created_at ? (
                            <ClientTime value={run.created_at} format="date_time" />
                          ) : (
                            "—"
                          )}
                        </span>
                      </span>
                    }
                    endContent={<ResultActions run={run} onDelete={requestDelete} />}
                  />
                ))}
              </List>
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
      {runToDelete ? (
        <ConfirmDialogControlled
          open
          onOpenChange={(open) => {
            if (!open) {
              const opener = menuAnchor.current;
              setRunToDelete(null);
              rescueFocus(() => (opener?.isConnected ? opener : listRef.current));
            }
          }}
          title={t("delete_result")}
          description={t("confirm_delete_result", {
            resultTitle: getResultTitle(runToDelete, labels)
          })}
          confirmLabel={deleteRun.isPending ? t("deleting") : t("delete")}
          pending={deleteRun.isPending}
          onConfirm={() => deleteRun.mutate(runToDelete)}
        />
      ) : null}
    </>
  );
}
