"use client";

import { List, ListItem } from "@astryxdesign/core/List";
import { useJobEventsConnected } from "@/features/jobs/job-events";
import { useMutation, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { FileText, MoreHorizontal, Paperclip, Trash2 } from "lucide-react";
import Link from "@/lib/link";
import { useTranslations } from "use-intl";
import { useRef, useState } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { EmptyState } from "@/components/composites/empty-state";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { pollWhile } from "@/lib/api/query";
import { ClientTime, useClientTimeText } from "@/components/composites/client-time";
import { toastApiError } from "@/lib/api/toast";
import { useFocusAcrossLayouts } from "@/lib/hooks/use-focus-across-layouts";
import { PHONE_QUERY, useMediaMatch } from "@/lib/hooks/use-media-match";
import { appRunsQueryOptions, getResultTitle, isRunActive, type AppRunSparse } from "../apps";
import { AppRunStatusToken } from "../status-token";

const RESULTS_POLL_MS = 5_000;

function resultTitleLabels(t: (key: string) => string) {
  return { inputPrefix: t("input"), empty: t("app_run_no_input_title") };
}

function ResultActions({ appId, run }: { appId: string; run: AppRunSparse }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [showDelete, setShowDelete] = useState(false);
  const titleLabels = resultTitleLabels(t);
  // A run has no name of its own; its row shows when it was made, so the
  // menu is named by that time in the viewer's time zone.
  const time = useClientTimeText(run.created_at, "date_time");

  const deleteRun = useMutation({
    mutationFn: () =>
      unwrap(browserApi.DELETE("/api/v1/app-runs/{id}/", { params: { path: { id: run.id } } })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["apps", appId, "runs"] });
      setShowDelete(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
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

/** `wrap`: a phone row shows the whole input, wrapped; the table cuts it at 40 characters. */
function ResultInputCell({ run, wrap = false }: { run: AppRunSparse; wrap?: boolean }) {
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
        <span
          className={wrap ? "flex items-start gap-1.5" : "flex max-w-[40ch] items-center gap-1.5"}
        >
          <FileText className="text-muted-foreground size-4 shrink-0" />
          <span className={wrap ? "break-words" : "truncate"}>
            {t("input")}: {text}
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
  const box = useRef<HTMLDivElement>(null);
  useFocusAcrossLayouts(box, phone);
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

  if (runs.length === 0) {
    return <EmptyState title={t("no_previous_results_found")} />;
  }

  if (phone) {
    // A phone (decision 9): one row per run, its whole input wrapped, the state and time
    // under it and the menu at the end; the table is a desktop layout.
    return (
      <div ref={box}>
        <List hasDividers edgeCompensation="inline" aria-label={t("results")}>
          {runs.map((run) => (
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
              endContent={<ResultActions appId={appId} run={run} />}
            />
          ))}
        </List>
      </div>
    );
  }

  return (
    <div ref={box} className="overflow-x-auto">
      {/* The runs fill the app page's "Resultat" tab, so the table takes its name. */}
      <Table aria-label={t("results")}>
        <TableHeader>
          <TableRow>
            <TableHead>{t("name")}</TableHead>
            <TableHead>{t("status")}</TableHead>
            <TableHead>{t("created")}</TableHead>
            <TableHead className="w-12">
              <span className="sr-only">{t("actions")}</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {runs.map((run) => (
            <TableRow key={run.id}>
              <TableCell>
                <Link href={resultHref(run.id)} className="hover:underline">
                  <ResultInputCell run={run} />
                </Link>
              </TableCell>
              <TableCell>
                <AppRunStatusToken status={run.status} />
              </TableCell>
              <TableCell className="text-muted-foreground font-mono text-sm">
                {run.created_at ? <ClientTime value={run.created_at} format="date_time" /> : "—"}
              </TableCell>
              <TableCell>
                <ResultActions appId={appId} run={run} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
