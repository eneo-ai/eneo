"use client";

import { useMutation, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { FileText, MoreHorizontal, Paperclip, Trash2 } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";
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
import { formatDateTime } from "@/lib/format";
import { toastApiError } from "@/lib/api/toast";
import { appRunsQueryOptions, getResultTitle, isRunActive, type AppRunSparse } from "../apps";
import { AppRunStatusBadge } from "../status-badge";

const RESULTS_POLL_MS = 5_000;

function ResultActions({ appId, run }: { appId: string; run: AppRunSparse }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [showDelete, setShowDelete] = useState(false);

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
          <Button variant="ghost" size="icon" aria-label={t("actions")}>
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
        description={t("confirm_delete_result", { resultTitle: getResultTitle(run) })}
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
  const { data: runs } = useSuspenseQuery({
    ...appRunsQueryOptions(browserApi, appId),
    refetchInterval: (query) =>
      query.state.data?.some((run) => isRunActive(run.status)) ? RESULTS_POLL_MS : false
  });

  if (runs.length === 0) {
    return <EmptyState title={t("no_previous_results_found")} />;
  }

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("name")}</TableHead>
            <TableHead>{t("status")}</TableHead>
            <TableHead>{t("created")}</TableHead>
            <TableHead className="w-12" />
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
                <AppRunStatusBadge status={run.status} />
              </TableCell>
              <TableCell className="text-muted-foreground font-mono text-sm">
                {formatDateTime(run.created_at)}
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
