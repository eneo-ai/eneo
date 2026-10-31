"use client";

import { Button } from "@astryxdesign/core/Button";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { Link } from "@astryxdesign/core/Link";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { useInfiniteQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useTranslations } from "use-intl";
import { useId, useState } from "react";
import { useClientTimeText } from "@/components/composites/client-time";
import { LoadMore, QueryStateBoundary } from "@/components/composites/query-state";
import { browserApi } from "@/lib/api/browser";
import { flattenPages } from "@/lib/api/pagination";
import {
  crawlFailureReasonHelp,
  crawlFailureReasonLabel,
  crawlRunFailureMessageKey,
  isActiveCrawlRun,
  resourceLink,
  type CrawlFailureKind
} from "./crawl-run-state";
import { CrawlRunCounts, CrawlRunStatusLabel } from "./crawl-run-ui";
import { crawlFailuresQueryOptions, type CrawlFailurePage, type CrawlRun } from "./knowledge";

/** Query options for a run's failures of one kind (all kinds with `null`). */
export type CrawlFailuresQuery = (
  runId: string,
  kind: CrawlFailureKind | null
) => ReturnType<typeof crawlFailuresQueryOptions>;

const defaultFailuresQuery: CrawlFailuresQuery = (runId, kind) =>
  crawlFailuresQueryOptions(browserApi, runId, kind);

const ORIGIN_KEYS: Record<CrawlRun["origin"], string> = {
  manual: "crawl_origin_manual",
  scheduled: "crawl_origin_scheduled",
  legacy: "crawl_origin_legacy"
};

export type CrawlRunDetailsContentProps = {
  run: CrawlRun;
  /** Which failures to show first: pages, files or all (`null`). */
  initialKind?: CrawlFailureKind | null;
  /** Group the website Problems view by cause; historical dialogs keep a flat list. */
  grouped?: boolean;
  /** Where the failures come from; the admin page reads them from its own endpoint. */
  failuresQuery?: CrawlFailuresQuery;
  /** Refreshes the caller's run too (the admin dialog's metadata); the failures reload regardless. */
  onRefresh?: () => Promise<unknown> | void;
  /** The run as the failures endpoint last saw it, so the caller's copy can follow. */
  onRunUpdate?: (run: CrawlRun) => void;
};

/**
 * What a run did and which addresses failed, loaded from the failures
 * endpoint while the dialog is open: the run's counts, how it was started,
 * why it ended as it did, the reasons across the run (with what to do about
 * them) and the failed addresses a page at a time, filtered by kind.
 */
export function CrawlRunDetailsContent({
  run,
  initialKind = null,
  grouped = false,
  failuresQuery = defaultFailuresQuery,
  onRefresh,
  onRunUpdate
}: CrawlRunDetailsContentProps) {
  const t = useTranslations();
  const headingId = useId();
  const [kind, setKind] = useState<CrawlFailureKind | null>(initialKind);
  const failures = useInfiniteQuery(failuresQuery(run.id, kind));

  const pages = failures.data?.pages;
  const lastPage = pages?.at(-1);
  // The failures endpoint returns the run as it is now: newer than the
  // list the dialog was opened from while the run is still going.
  const displayedRun = lastPage?.run ?? run;
  const items = flattenPages<CrawlFailurePage["items"][number]>(pages);
  const total = lastPage?.total_count ?? 0;
  const detailsAvailable = lastPage?.details_available ?? true;
  const summary = Object.entries(displayedRun.failure_summary ?? {});
  const reasons = [
    ...new Set([
      ...(kind ? [] : summary.map(([reason]) => reason)),
      ...items.map((item) => item.reason)
    ])
  ];
  const failureMessageKey = crawlRunFailureMessageKey(displayedRun);
  const loading = failures.isPending || failures.isFetchingNextPage;
  const refreshing = failures.isRefetching;

  function refresh() {
    if (loading || refreshing) return;
    void failures.refetch().then((result) => {
      const refreshed = result.data?.pages.at(-1)?.run;
      if (refreshed) onRunUpdate?.(refreshed);
    });
    void onRefresh?.();
  }

  const kinds: { value: "all" | CrawlFailureKind; label: string }[] = [
    { value: "all", label: t("crawl_failures_filter_all") },
    { value: "page", label: t("crawl_counts_pages") },
    { value: "file", label: t("crawl_counts_files") }
  ];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CrawlRunStatusLabel run={displayedRun} />
          <Button
            size="sm"
            label={t("refresh")}
            icon={<RefreshCw aria-hidden="true" />}
            isLoading={refreshing}
            isInterruptible
            onClick={refresh}
          />
        </div>
        <div className="max-w-sm">
          <CrawlRunCounts run={displayedRun} onShowFailures={setKind} />
        </div>
        <p className="text-ax-text-secondary text-sm">{t(ORIGIN_KEYS[displayedRun.origin])}</p>
        {isActiveCrawlRun(displayedRun) ? (
          <p className="text-ax-text-secondary text-xs">{t("crawl_details_running")}</p>
        ) : null}
        {failureMessageKey ? (
          <p className="text-ax-text-secondary text-sm">{t(failureMessageKey)}</p>
        ) : null}
      </div>

      <div className="border-ax-border flex flex-wrap items-center justify-between gap-2 border-t pt-3">
        <h3 id={headingId} className="text-sm font-semibold">
          {t("crawl_failed_addresses")}
        </h3>
        <SegmentedControl
          size="sm"
          label={t("crawl_failure_resource_type")}
          value={kind ?? "all"}
          onChange={(value) => setKind(value === "page" || value === "file" ? value : null)}
        >
          {kinds.map((option) => (
            <SegmentedControlItem key={option.value} value={option.value} label={option.label} />
          ))}
        </SegmentedControl>
      </div>

      {!grouped && summary.length > 0 ? (
        <Collapsible trigger={t("crawl_failure_help_title")} defaultIsOpen={false}>
          <ul className="flex flex-col gap-3 text-sm">
            {summary.map(([reason, count]) => {
              const help = crawlFailureReasonHelp(t, reason);
              return (
                <li key={reason}>
                  <p className="font-medium">
                    {crawlFailureReasonLabel(t, reason)} · {count}
                  </p>
                  {help ? (
                    <p className="text-ax-text-secondary mt-0.5 max-w-prose">{help}</p>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </Collapsible>
      ) : null}

      <QueryStateBoundary query={failures} rows={3} errorTitle={t("crawl_failures_load_failed")}>
        {() =>
          grouped && reasons.length > 0 ? (
            <div className="divide-ax-border divide-y">
              {reasons.map((reason, index) => {
                const matching = items.filter((item) => item.reason === reason);
                const reasonTotal = kind ? undefined : displayedRun.failure_summary?.[reason];
                const help = crawlFailureReasonHelp(t, reason);
                const groupHeadingId = `${headingId}-${index}`;
                return (
                  <section
                    key={reason}
                    aria-labelledby={groupHeadingId}
                    className="flex flex-col gap-2 py-4"
                  >
                    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                      <h4 id={groupHeadingId} className="text-sm font-semibold">
                        {crawlFailureReasonLabel(t, reason)}
                      </h4>
                      <p className="text-ax-text-secondary text-xs tabular-nums">
                        {reasonTotal === undefined
                          ? t("website_source_problem_shown", { shown: matching.length })
                          : t("website_source_problem_count", {
                              shown: matching.length,
                              total: reasonTotal
                            })}
                      </p>
                    </div>
                    {help && <p className="text-ax-text-secondary max-w-prose text-sm">{help}</p>}
                    {matching.length > 0 ? (
                      <FailureList
                        items={matching}
                        labelledBy={groupHeadingId}
                        showReason={false}
                      />
                    ) : (
                      <p className="text-ax-text-secondary text-sm">
                        {t(
                          detailsAvailable
                            ? "website_source_problem_not_loaded"
                            : "crawl_failures_unavailable"
                        )}
                      </p>
                    )}
                  </section>
                );
              })}
            </div>
          ) : items.length > 0 ? (
            <FailureList items={items} labelledBy={headingId} />
          ) : (
            <p className="text-ax-text-secondary py-4 text-sm">
              {detailsAvailable
                ? kind
                  ? t("crawl_failures_filter_empty")
                  : t("crawl_failures_empty")
                : t("crawl_failures_unavailable")}
            </p>
          )
        }
      </QueryStateBoundary>
      <LoadMore
        query={failures}
        label={t("crawl_failures_load_more", { current: items.length, total })}
      />
    </div>
  );
}

function FailureList({
  items,
  labelledBy,
  showReason = true
}: {
  items: CrawlFailurePage["items"];
  labelledBy: string;
  showReason?: boolean;
}) {
  const t = useTranslations();
  return (
    <ul aria-labelledby={labelledBy} className="divide-ax-border divide-y text-sm">
      {items.map((failure) => {
        const href = resourceLink(failure.url);
        return (
          <li key={failure.id} className="flex flex-col gap-1.5 py-3">
            <p className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <span className="text-ax-text-secondary text-xs">
                {failure.kind === "page" ? t("page") : t("crawl_failure_file")}
              </span>
              {showReason && (
                <span className="text-ax-error break-words">
                  {crawlFailureReasonLabel(t, failure.reason)}
                </span>
              )}
            </p>
            {href ? (
              <Link href={href} isExternalLink hasUnderline>
                <span className="break-all">{failure.url}</span>
              </Link>
            ) : (
              <span className="break-all">{failure.url}</span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * The run details in an Astryx dialog, opened from a status cell or a run
 * row. `onRerun` adds "Kör om hela webbplatsen", which closes the dialog and
 * hands over to the caller's start flow.
 */
export function CrawlRunDetailsDialog({
  run,
  isOpen,
  onOpenChange,
  initialKind = null,
  failuresQuery,
  onRerun
}: {
  run: CrawlRun;
  isOpen: boolean;
  onOpenChange: (isOpen: boolean) => void;
  initialKind?: CrawlFailureKind | null;
  failuresQuery?: CrawlFailuresQuery;
  onRerun?: () => void;
}) {
  const t = useTranslations();
  const date = useClientTimeText(run.created_at, "date_time");

  return (
    <Dialog isOpen={isOpen} onOpenChange={onOpenChange} width={720} maxHeight="85dvh">
      <Layout
        height="auto"
        header={
          <DialogHeader
            title={t("crawl_details_title", { date: date ?? "" })}
            subtitle={t("crawl_details_description")}
            onOpenChange={onOpenChange}
          />
        }
        content={
          <LayoutContent>
            {isOpen ? (
              // Keyed so a different run or kind starts from its own filter.
              <CrawlRunDetailsContent
                key={`${run.id}-${initialKind ?? "all"}`}
                run={run}
                initialKind={initialKind}
                failuresQuery={failuresQuery}
              />
            ) : null}
          </LayoutContent>
        }
        footer={
          onRerun ? (
            <LayoutFooter>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-ax-text-secondary text-xs">
                  {t("crawl_retry_whole_website_help")}
                </p>
                <Button
                  label={t("crawl_retry_whole_website")}
                  onClick={() => {
                    onOpenChange(false);
                    onRerun();
                  }}
                />
              </div>
            </LayoutFooter>
          ) : undefined
        }
      />
    </Dialog>
  );
}
