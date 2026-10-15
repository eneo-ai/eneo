"use client";

import { Button } from "@astryxdesign/core/Button";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { Timestamp } from "@astryxdesign/core/Timestamp";
import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import { Check, History, LoaderCircle, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useRef, useState } from "react";
import { ClientTime } from "@/components/composites/client-time";
import { EmptyState } from "@/components/composites/empty-state";
import { LoadingState } from "@/components/composites/loading-state";
import { ListError } from "@/components/composites/query-state";
import { browserApi } from "@/lib/api/browser";
import { formatDuration } from "@/lib/format";
import { rescueFocus } from "@/lib/focus-rescue";
import { useHydrated } from "@/lib/hooks/use-hydrated";
import { cn } from "@/lib/utils";
import type { IntegrationKnowledge } from "../../knowledge";
import { recentSyncLogsQueryOptions, type SyncLog } from "../queries";
import { describeSkipReason } from "../skip-reasons";
import { isCredentialsError } from "../source-problems";
import {
  activityKind,
  groupActivityByDay,
  mergeActivity,
  readSyncLogExtras,
  skippedNotListed,
  summarizeActivity,
  type ActivityDay,
  type ActivityEntry,
  type ActivityKind,
  type FileChange
} from "../sync-activity";

const PAGE_SIZE = 10;

const ICON_STYLE: Record<ActivityKind, string> = {
  failed: "bg-ax-error-muted text-ax-error",
  running: "bg-ax-accent-muted text-ax-text-accent",
  changed: "bg-ax-success-muted text-ax-success",
  unchanged: "bg-ax-muted text-ax-text-secondary"
};

const CHANGE_STYLE: Record<FileChange["change"], string> = {
  added: "text-ax-success",
  updated: "text-ax-text-accent",
  deleted: "text-ax-error"
};

const CHANGE_LABEL: Record<FileChange["change"], string> = {
  added: "integration_activity_change_added",
  updated: "integration_activity_change_updated",
  deleted: "integration_activity_change_deleted"
};

const DETAILS_CLASS =
  "[&_.astryx-collapsible-trigger]:text-ax-text-secondary [&_.astryx-collapsible-trigger]:min-h-6 [&_.astryx-collapsible-trigger]:text-xs [&_.astryx-collapsible-trigger]:font-medium pointer-coarse:[&_.astryx-collapsible-trigger]:min-h-11";

type Translate = ReturnType<typeof useTranslations>;

function syncTitle(log: SyncLog, kind: ActivityKind, t: Translate): string {
  switch (kind) {
    case "failed":
      return t("integration_activity_failed");
    case "running":
      return t("integration_activity_running");
    case "unchanged":
      return t("integration_activity_unchanged");
    case "changed": {
      const parts: string[] = [];
      if (log.files_processed > 0) parts.push(t("file_s_synced", { count: log.files_processed }));
      if (log.pages_processed > 0) parts.push(t("page_s_synced", { count: log.pages_processed }));
      if (log.files_deleted > 0) parts.push(t("file_s_deleted", { count: log.files_deleted }));
      if (log.skipped_items > 0) parts.push(t("item_s_skipped", { count: log.skipped_items }));
      const unchanged = readSyncLogExtras(log).unchangedItems;
      if (parts.length === 0 && unchanged > 0) {
        parts.push(t("item_s_unchanged", { count: unchanged }));
      }
      return parts.join(", ");
    }
  }
}

/** How long the sync took; a sync under a second reads as one second. */
function syncDuration(log: SyncLog): string | null {
  if (!log.completed_at) return null;
  const start = Date.parse(log.started_at);
  const end = Date.parse(log.completed_at);
  if (Number.isNaN(start) || Number.isNaN(end)) return null;
  return formatDuration(log.started_at, new Date(Math.max(end, start + 1000)).toISOString());
}

// ClientTime has no time-of-day format; this renders the same Timestamp the
// same way (after hydration, no hover card) with Astryx's "time" format.
function TimeOfDay({ value }: { value: string }) {
  const hydrated = useHydrated();
  if (!hydrated) return null;
  return (
    <Timestamp value={value} format="time" type="inherit" color="inherit" hasTooltip={false} />
  );
}

function KindIcon({ kind }: { kind: ActivityKind }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "flex size-7 shrink-0 items-center justify-center rounded-full",
        ICON_STYLE[kind]
      )}
    >
      {kind === "failed" ? (
        <X className="size-3.5" />
      ) : kind === "running" ? (
        <LoaderCircle className="size-3.5 motion-safe:animate-spin" />
      ) : (
        <Check className="size-3.5" />
      )}
    </span>
  );
}

function SyncFiles({ log }: { log: SyncLog }) {
  const t = useTranslations();
  const extras = readSyncLogExtras(log);
  const skipped = log.skipped_details ?? [];
  if (extras.changedFiles.length === 0 && skipped.length === 0) return null;
  const notListed =
    skippedNotListed(log) + Math.max(0, extras.changedTotal - extras.changedFiles.length);
  return (
    <Collapsible
      trigger={t("integration_activity_show_files", {
        count: extras.changedTotal + log.skipped_items
      })}
      defaultIsOpen={false}
      chevronPosition="start"
      className={DETAILS_CLASS}
    >
      <ul className="flex flex-col gap-0.5 ps-1 text-xs">
        {/* The same file name recurs across folders, so the key needs the position. */}
        {extras.changedFiles.map((change, index) => (
          <li key={`c${index}:${change.file}`} className="flex gap-2">
            <span className={cn("w-20 shrink-0 font-medium", CHANGE_STYLE[change.change])}>
              {t(CHANGE_LABEL[change.change])}
            </span>
            <span className="text-ax-text min-w-0 break-all">{change.file}</span>
          </li>
        ))}
        {skipped.map((detail, index) => (
          <li key={`s${index}:${detail.file}`} className="flex gap-2">
            <span className="text-ax-warning w-20 shrink-0 font-medium">
              {t("integration_activity_change_skipped")}
            </span>
            <span className="min-w-0 break-all">
              <span className="text-ax-text">{detail.file}</span>{" "}
              <span className="text-ax-text-secondary">
                – {describeSkipReason(detail.reason, t)}
              </span>
            </span>
          </li>
        ))}
        {notListed > 0 ? (
          <li className="text-ax-text-secondary italic">
            {t("skipped_and_n_more", { count: notListed })}
          </li>
        ) : extras.skippedTruncated ? (
          <li className="text-ax-text-secondary italic">{t("skipped_list_truncated")}</li>
        ) : null}
      </ul>
    </Collapsible>
  );
}

function ActivityRow({ entry, showFolders }: { entry: ActivityEntry; showFolders: boolean }) {
  const t = useTranslations();
  const { log, item } = entry;
  const kind = activityKind(log);
  const extras = readSyncLogExtras(log);
  const failure = log.error_message
    ? isCredentialsError(log.error_message)
      ? t("integration_problem_credentials_title")
      : log.error_message
    : null;
  const details = [
    showFolders ? item.name : null,
    log.sync_type === "full" ? t("full_sync") : t("delta_sync"),
    syncDuration(log)
  ].filter((part): part is string => part !== null);

  return (
    <li className="border-ax-border flex gap-3 border-t py-3">
      <span className="text-ax-text-secondary w-11 shrink-0 pt-1.5 text-xs tabular-nums">
        <TimeOfDay value={log.started_at} />
      </span>
      <KindIcon kind={kind} />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="font-medium">{syncTitle(log, kind, t)}</p>
        {failure ? <p className="text-ax-error text-sm break-words">{failure}</p> : null}
        {extras.reconcileWarning ? (
          <p className="text-ax-warning text-sm">
            <span className="font-medium">{t("sync_reconcile_warning")}:</span>{" "}
            {extras.reconcileWarning}
          </p>
        ) : null}
        <p className="text-ax-text-secondary text-xs">{details.join(" · ")}</p>
        <SyncFiles log={log} />
      </div>
    </li>
  );
}

function ActivityDaySection({ day, showFolders }: { day: ActivityDay; showFolders: boolean }) {
  const headingId = useId();
  const first = day.entries[0];
  return (
    <section aria-labelledby={headingId} className="flex flex-col">
      <h2
        id={headingId}
        className="text-ax-text-secondary pb-2 text-xs font-semibold tracking-wide uppercase"
      >
        {first ? <ClientTime value={first.log.started_at} format="date" /> : null}
      </h2>
      <ol className="flex flex-col">
        {day.entries.map((entry) => (
          <ActivityRow key={entry.log.id} entry={entry} showFolders={showFolders} />
        ))}
      </ol>
    </section>
  );
}

function Total({
  label,
  value,
  isAlert = false
}: {
  label: string;
  value: number;
  isAlert?: boolean;
}) {
  return (
    <div>
      <dt className="text-ax-text-secondary text-xs">{label}</dt>
      <dd className={cn("text-lg font-semibold tabular-nums", isAlert && "text-ax-error")}>
        {value}
      </dd>
    </div>
  );
}

/**
 * A source's sync history as one timeline, newest first and grouped by day,
 * with totals beside it. Loads each item's newest syncs; "show older" grows
 * the window for every item, and only once all of them loaded.
 */
export function ActivityView({
  items,
  showFolders
}: {
  items: IntegrationKnowledge[];
  /** The source has more than one item, so each entry names its folder. */
  showFolders: boolean;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const totalsId = useId();
  const eventsRef = useRef<HTMLElement>(null);
  const [limit, setLimit] = useState(PAGE_SIZE);

  const results = useQueries({
    queries: items.map((item) => recentSyncLogsQueryOptions(browserApi, item.id, limit))
  });
  // Kept apart from the mutation's own error, which a retry clears at once:
  // the banner (and the focused retry button in it) stays until one succeeds.
  const [olderError, setOlderError] = useState<unknown>(null);
  // The window only grows once every item's bigger page loaded, so a failure
  // keeps the timeline that is already shown.
  const older = useMutation({
    mutationFn: (next: number) =>
      Promise.all(
        items.map((item) =>
          queryClient.query(recentSyncLogsQueryOptions(browserApi, item.id, next))
        )
      ),
    onSuccess: (_pages, next) => {
      setLimit(next);
      setOlderError(null);
      // The button goes once nothing older is left, the banner once a retry worked.
      rescueFocus(eventsRef.current);
    },
    onError: (error) => setOlderError(error)
  });

  const pages = results.map((result) => result.data);
  const isLoaded = pages.every((page) => page !== undefined);
  const failed = results.filter((result) => result.isError);
  const entries = isLoaded
    ? mergeActivity(
        items.map((item, index) => ({
          item,
          logs: pages[index]?.items ?? [],
          total: pages[index]?.total_count
        }))
      )
    : [];
  const days = groupActivityByDay(entries);
  const totals = summarizeActivity(entries);
  const hasMore = isLoaded && pages.some((page) => page && page.total_count > page.items.length);
  const syncCount = pages.reduce((sum, page) => sum + (page?.total_count ?? 0), 0);

  return (
    <div className="flex flex-wrap items-start gap-8">
      <section
        ref={eventsRef}
        tabIndex={-1}
        aria-label={t("integration_activity_events")}
        className="flex min-w-0 flex-[999_1_32rem] flex-col gap-6"
      >
        {failed.length > 0 ? (
          <ListError
            title={t("sync_history_load_failed")}
            error={failed[0]?.error}
            isRetrying={failed.some((result) => result.isFetching)}
            onRetry={() => {
              for (const result of failed) void result.refetch();
            }}
          />
        ) : olderError !== null ? (
          <ListError
            title={t("sync_history_load_failed")}
            error={olderError}
            isRetrying={older.isPending}
            onRetry={() => older.mutate(limit + PAGE_SIZE)}
          />
        ) : null}

        {!isLoaded ? (
          failed.length === 0 ? (
            <LoadingState label={t("loading_sync_history")} rows={4} />
          ) : null
        ) : entries.length === 0 ? (
          <EmptyState icon={<History />} title={t("integration_sync_summary_none")} isCompact />
        ) : (
          days.map((day) => (
            <ActivityDaySection key={day.day} day={day} showFolders={showFolders} />
          ))
        )}

        {hasMore ? (
          <Button
            label={t("integration_activity_show_older")}
            isLoading={older.isPending}
            isInterruptible
            onClick={() => {
              if (!older.isPending) older.mutate(limit + PAGE_SIZE);
            }}
            className="w-fit"
          />
        ) : null}
      </section>

      {entries.length > 0 ? (
        <section
          aria-labelledby={totalsId}
          className="border-ax-border rounded-ax-container flex flex-[1_1_16rem] flex-col gap-3 border p-4 lg:max-w-xs"
        >
          <div className="flex flex-col gap-0.5">
            <h2 id={totalsId} className="text-sm font-semibold">
              {t("integration_activity_totals_heading", { count: totals.syncs })}
            </h2>
            {syncCount > totals.syncs ? (
              <p className="text-ax-text-secondary text-xs">
                {t("integration_activity_totals_of_all", { total: syncCount })}
              </p>
            ) : null}
          </div>
          <dl className="grid grid-cols-2 gap-3">
            <Total
              label={t("integration_activity_totals_failed")}
              value={totals.failed}
              isAlert={totals.failed > 0}
            />
            <Total label={t("integration_activity_totals_changed")} value={totals.changedFiles} />
            <Total label={t("integration_activity_totals_unchanged")} value={totals.unchanged} />
            <Total label={t("integration_activity_totals_deleted")} value={totals.deleted} />
          </dl>
        </section>
      ) : null}
    </div>
  );
}
