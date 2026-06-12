"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Check, History, Loader2, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Spinner } from "@/components/ui/spinner";
import { browserApi } from "@/lib/api/browser";
import { formatDateTime, formatDuration } from "@/lib/format";
import type { IntegrationKnowledge } from "../knowledge";
import { syncLogsQueryOptions, type SyncLog } from "./queries";

type Translate = (key: string, params?: Record<string, string>) => string;

function syncSummary(log: SyncLog, t: Translate): string {
  const parts: string[] = [];
  if (log.files_processed > 0)
    parts.push(t("file_s_synced", { count: String(log.files_processed) }));
  if (log.files_deleted > 0) parts.push(t("file_s_deleted", { count: String(log.files_deleted) }));
  if (log.pages_processed > 0)
    parts.push(t("page_s_synced", { count: String(log.pages_processed) }));
  if (log.skipped_items > 0) parts.push(t("item_s_skipped", { count: String(log.skipped_items) }));
  return parts.length > 0 ? parts.join(", ") : t("no_changes");
}

function StatusBadge({ status }: { status: string }) {
  const className =
    status === "success"
      ? "bg-green-50 text-green-800 dark:bg-green-950 dark:text-green-300"
      : status === "error"
        ? "bg-red-50 text-red-800 dark:bg-red-950 dark:text-red-300"
        : "bg-amber-50 text-amber-800 dark:bg-amber-950 dark:text-amber-300";
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${className}`}>{status}</span>
  );
}

function SyncLogEntry({ log }: { log: SyncLog }) {
  const t = useTranslations();
  return (
    <div className="rounded-lg border p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          {log.status === "success" ? (
            <Check className="size-4 shrink-0 text-green-600 dark:text-green-400" />
          ) : log.status === "error" ? (
            <X className="size-4 shrink-0 text-red-600 dark:text-red-400" />
          ) : (
            <Loader2 className="size-4 shrink-0 animate-spin text-amber-600 dark:text-amber-400" />
          )}
          <span className="text-sm font-medium">
            {log.sync_type === "full" ? t("full_sync") : t("delta_sync")}
          </span>
          <StatusBadge status={log.status} />
        </div>
        <span className="text-muted-foreground shrink-0 text-xs">
          {formatDateTime(log.started_at)}
        </span>
      </div>
      <div className="text-muted-foreground mb-1 text-xs">{syncSummary(log, t)}</div>
      {log.skipped_items > 0 && log.skipped_details.length > 0 && (
        <details className="mb-1">
          <summary className="cursor-pointer text-xs text-amber-600 hover:underline dark:text-amber-400">
            {t("item_s_skipped", { count: String(log.skipped_items) })}
          </summary>
          <ul className="text-muted-foreground mt-1 ml-4 flex flex-col gap-0.5 text-xs">
            {log.skipped_details.map((detail) => (
              <li key={detail.file} className="flex min-w-0 gap-1">
                <span className="max-w-[200px] truncate font-medium" title={detail.file}>
                  {detail.file}
                </span>
                <span>—</span>
                <span className="truncate">{detail.reason}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
      <div className="text-muted-foreground flex items-center gap-4 text-xs">
        <span>
          {t("duration")}:{" "}
          {log.completed_at ? formatDuration(log.started_at, log.completed_at) : "—"}
        </span>
        {log.error_message && (
          <span className="font-medium text-red-600 dark:text-red-400">
            {t("error")}: {log.error_message}
          </span>
        )}
      </div>
    </div>
  );
}

/**
 * Paginated sync history for one integration knowledge item; open while
 * `item` is set. Keyed remount resets the page when the item changes.
 */
export function SyncHistoryDialog({
  item,
  onOpenChange
}: {
  item: IntegrationKnowledge | null;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={item !== null} onOpenChange={onOpenChange}>
      {item && <SyncHistoryContent key={item.id} item={item} />}
    </Dialog>
  );
}

function SyncHistoryContent({ item }: { item: IntegrationKnowledge }) {
  const t = useTranslations();
  const [page, setPage] = useState(1);

  const { data, isPending, isError, error } = useQuery({
    ...syncLogsQueryOptions(browserApi, item.id, page),
    placeholderData: keepPreviousData
  });

  const logs = data?.items ?? [];
  const totalPages = data?.total_pages ?? 1;
  const successful = logs.filter((log) => log.status === "success");

  return (
    <DialogContent className="max-w-2xl">
      <DialogHeader>
        <DialogTitle>
          {t("sync_history")} — {item.name}
        </DialogTitle>
      </DialogHeader>
      <div className="flex max-h-[60vh] flex-col gap-3 overflow-y-auto pr-1">
        {isPending ? (
          <div className="flex items-center justify-center gap-2 py-8">
            <Spinner />
          </div>
        ) : isError ? (
          <div className="flex items-center gap-2 rounded-md bg-red-50 p-4 text-sm text-red-800 dark:bg-red-950 dark:text-red-300">
            <X className="size-4 shrink-0" />
            <span>{error instanceof Error ? error.message : t("error")}</span>
          </div>
        ) : logs.length === 0 ? (
          <div className="text-muted-foreground flex flex-col items-center gap-2 py-8">
            <History className="size-6 opacity-50" />
            <p className="text-sm">{t("integration_sync_summary_none")}</p>
          </div>
        ) : (
          <>
            <div className="flex flex-col gap-2 rounded-lg border p-4 text-sm">
              <div className="flex items-center justify-between">
                <span className="font-semibold">{t("overall_statistics")}</span>
                <span className="text-muted-foreground text-xs">
                  {t("total_syncs")}: {data.total_count}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-x-6 gap-y-1">
                <Stat label={t("page")} value={`${page} / ${totalPages}`} />
                <Stat label={t("total_syncs")} value={String(successful.length)} />
                <Stat
                  label={t("files_synced")}
                  value={String(sum(successful, (log) => log.files_processed))}
                />
                <Stat
                  label={t("files_deleted")}
                  value={String(sum(successful, (log) => log.files_deleted))}
                />
                <Stat
                  label={t("pages_synced")}
                  value={String(sum(successful, (log) => log.pages_processed))}
                />
              </div>
            </div>
            {logs.map((log) => (
              <SyncLogEntry key={log.id} log={log} />
            ))}
          </>
        )}
      </div>
      {totalPages > 1 && (
        <DialogFooter className="sm:justify-start">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1 || isPending}
            onClick={() => setPage((current) => current - 1)}
          >
            {t("previous")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= totalPages || isPending}
            onClick={() => setPage((current) => current + 1)}
          >
            {t("next")}
          </Button>
        </DialogFooter>
      )}
    </DialogContent>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <span className="text-muted-foreground">{label}:</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}

function sum(logs: SyncLog[], pick: (log: SyncLog) => number): number {
  return logs.reduce((total, log) => total + pick(log), 0);
}
