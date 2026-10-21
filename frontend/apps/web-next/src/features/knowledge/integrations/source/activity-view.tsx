"use client";

import { Button } from "@astryxdesign/core/Button";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { useCollator } from "@astryxdesign/core/i18n";
import { Selector } from "@astryxdesign/core/Selector";
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
import { useFocusRescue } from "@/lib/focus-rescue";
import { useHydrated } from "@/lib/hooks/use-hydrated";
import { cn } from "@/lib/utils";
import type { IntegrationKnowledge } from "../../knowledge";
import {
  addOlderSyncLogs,
  fetchSyncLogPage,
  shownSyncLogWindow,
  syncLogWindowQueryOptions,
  type SyncLog,
  type SyncLogWindow
} from "../queries";
import { describeSkipReason } from "../skip-reasons";
import { isCredentialsError } from "../source-problems";
import {
  activityKind,
  groupActivityByDay,
  itemsToPage,
  mergeActivity,
  readSyncLogExtras,
  skippedNotListed,
  summarizeActivity,
  type ActivityDay,
  type ActivityEntry,
  type ActivityKind,
  type FileChange
} from "../sync-activity";

/** "Every folder" in the folder selector; item ids are UUIDs. */
const ALL_FOLDERS = "all";

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

/** A shown folder's loaded history. */
type LoadedWindow = SyncLogWindow & { item: IntegrationKnowledge };

/** "Show older" for the folder selection it was pressed in (null: every folder). */
type OlderRequest = { selection: string | null; targets: LoadedWindow[] };

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
      const add = (count: number, one: () => string, other: (count: number) => string) => {
        if (count > 0) parts.push(count === 1 ? one() : other(count));
      };
      add(
        log.files_processed,
        () => t("integration_activity_files_synced_one"),
        (count) => t("integration_activity_files_synced_other", { count })
      );
      add(
        log.pages_processed,
        () => t("integration_activity_pages_synced_one"),
        (count) => t("integration_activity_pages_synced_other", { count })
      );
      add(
        log.files_deleted,
        () => t("integration_activity_files_deleted_one"),
        (count) => t("integration_activity_files_deleted_other", { count })
      );
      add(
        log.skipped_items,
        () => t("integration_activity_items_skipped_one"),
        (count) => t("integration_activity_items_skipped_other", { count })
      );
      if (parts.length === 0) {
        add(
          readSyncLogExtras(log).unchangedItems,
          () => t("integration_activity_items_unchanged_one"),
          (count) => t("integration_activity_items_unchanged_other", { count })
        );
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

/** The folder's name, or its path where another folder of the source has the same name. */
function folderLabel(item: IntegrationKnowledge, items: readonly IntegrationKnowledge[]): string {
  const sameName = items.filter((other) => other.name === item.name).length > 1;
  return sameName && item.folder_path ? item.folder_path : item.name;
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
  const count = extras.changedTotal + log.skipped_items;
  return (
    <Collapsible
      trigger={
        count === 1
          ? t("integration_activity_show_files_one")
          : t("integration_activity_show_files_other", { count })
      }
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
              <span className="text-ax-text-secondary">– {describeSkipReason(detail, t)}</span>
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
            {t.rich("integration_activity_reconcile_warning", {
              label: (chunks) => <span className="font-medium">{chunks}</span>,
              warning: extras.reconcileWarning
            })}
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
 * with totals beside it. Each folder's history loads a page at a time; "show
 * older" pages the folders the timeline waits for. Every folder at once stops
 * where the busiest one's loaded history runs out, so a quiet folder's older
 * syncs are reached by choosing it in the folder selector.
 */
export function ActivityView({
  spaceId,
  items,
  selectedId,
  onSelect
}: {
  spaceId: string;
  items: IntegrationKnowledge[];
  /** The one folder whose history to show; null shows every folder's. */
  selectedId: string | null;
  onSelect: (itemId: string | null) => void;
}) {
  const t = useTranslations();
  const collator = useCollator();
  const queryClient = useQueryClient();
  const totalsId = useId();
  const eventsRef = useRef<HTMLElement>(null);
  const rescue = useFocusRescue();

  const multiple = items.length > 1;
  const shown = selectedId ? items.filter((item) => item.id === selectedId) : items;
  const results = useQueries({
    queries: shown.map((item) => syncLogWindowQueryOptions(browserApi, queryClient, spaceId, item))
  });
  const loaded = shown.flatMap((item, index): LoadedWindow[] => {
    const result = results[index];
    // A new revision whose first page failed keeps the history shown before, beside the error.
    const data =
      result?.data ??
      (result?.isError ? shownSyncLogWindow(queryClient, spaceId, item.id) : undefined);
    return data ? [{ ...data, item }] : [];
  });

  // Kept apart from the mutation's own error, which a retry clears at once:
  // the banner (and the focused retry button in it) stays until one succeeds.
  // It and the busy state belong to the folder selection they came from.
  const [olderError, setOlderError] = useState<{
    selection: string | null;
    error: unknown;
  } | null>(null);
  const older = useMutation({
    mutationFn: ({ targets }: OlderRequest) =>
      Promise.all(
        targets.map(async (target) => ({
          target,
          page: await fetchSyncLogPage(browserApi, spaceId, target.item.id, target.logs.length)
        }))
      ),
    onSuccess: (pages, { selection }) => {
      for (const { target, page } of pages) {
        addOlderSyncLogs(queryClient, spaceId, target.item.id, page, target.logs.at(-1)?.id);
      }
      setOlderError((current) => (current?.selection === selection ? null : current));
      // The button goes once nothing older is left, the banner once a retry worked.
      rescue(eventsRef.current);
    },
    onError: (error, { selection }) => setOlderError({ selection, error })
  });
  const olderPending = older.isPending && older.variables.selection === selectedId;
  const olderFailure = olderError?.selection === selectedId ? olderError : null;
  const showOlder = () => {
    if (!olderPending) older.mutate({ selection: selectedId, targets: itemsToPage(loaded) });
  };

  const isLoaded = loaded.length === shown.length;
  const failed = results.filter((result) => result.isError);
  const entries = isLoaded ? mergeActivity(loaded) : [];
  const days = groupActivityByDay(entries);
  const totals = summarizeActivity(entries);
  const hasMore = isLoaded && loaded.some((window) => window.total > window.logs.length);
  const syncCount = loaded.reduce((sum, window) => sum + window.total, 0);
  const folderOptions = items
    .map((item) => ({ value: item.id, label: folderLabel(item, items) }))
    .sort((a, b) => collator.compare(a.label, b.label));

  return (
    <div className="flex flex-wrap items-start gap-8">
      <section
        ref={eventsRef}
        tabIndex={-1}
        aria-label={t("integration_activity_events")}
        className="flex min-w-0 flex-[999_1_32rem] flex-col gap-6"
      >
        {multiple ? (
          <div className="w-full max-w-xs">
            <Selector
              label={t("integration_source_folder")}
              options={[
                { value: ALL_FOLDERS, label: t("integration_source_all_folders") },
                ...folderOptions
              ]}
              value={selectedId ?? ALL_FOLDERS}
              onChange={(value) => {
                setOlderError(null);
                onSelect(value === ALL_FOLDERS ? null : value);
              }}
              size="sm"
              width="100%"
            />
          </div>
        ) : null}

        {failed.length > 0 ? (
          <ListError
            title={t("sync_history_load_failed")}
            error={failed[0]?.error}
            isRetrying={failed.some((result) => result.isFetching)}
            onRetry={() => {
              for (const result of failed) void result.refetch();
            }}
          />
        ) : olderFailure !== null ? (
          <ListError
            title={t("sync_history_load_failed")}
            error={olderFailure.error}
            isRetrying={olderPending}
            onRetry={showOlder}
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
            <ActivityDaySection key={day.day} day={day} showFolders={multiple && !selectedId} />
          ))
        )}

        {hasMore ? (
          <Button
            label={t("integration_activity_show_older")}
            isLoading={olderPending}
            isInterruptible
            onClick={showOlder}
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
              {totals.syncs === 1
                ? t("integration_activity_totals_heading_one")
                : t("integration_activity_totals_heading_other", { count: totals.syncs })}
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
