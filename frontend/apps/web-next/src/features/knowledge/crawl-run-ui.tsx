"use client";

import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { RefreshCw } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import {
  crawlRunFailureMessageKey,
  crawlRunState,
  hasCrawlIssues,
  isMinorPartial,
  type CrawlFailureKind
} from "./crawl-run-state";
import type { CrawlRun } from "./knowledge";
import { KnowledgeLabel } from "./table-controls-ui";
import { crawlRunStatus } from "./website-status";

/** Small parts shared by the website list, the website page and the admin crawler page. */

const STATES_WITH_REASON = new Set(["failed", "interrupted", "cancelled"]);

/** The run's state as a status dot and text, with why it failed or stopped. */
export function CrawlRunStatusLabel({ run }: { run: CrawlRun }) {
  const t = useTranslations();
  const status = crawlRunStatus(run);
  const reasonKey = STATES_WITH_REASON.has(crawlRunState(run))
    ? crawlRunFailureMessageKey(run)
    : null;
  return (
    <KnowledgeLabel
      tone={status.tone}
      label={t(status.labelKey)}
      detail={reasonKey ? t(reasonKey) : undefined}
      isPulsing={status.isPulsing}
    />
  );
}

/**
 * Links to what went wrong in a run: the failed pages and files by count, or
 * the details when the run itself failed. Each opens the run's details on the
 * failures of that kind.
 */
export function CrawlFailureActions({
  run,
  onSelect
}: {
  run: CrawlRun;
  onSelect: (kind: CrawlFailureKind | null) => void;
}) {
  const t = useTranslations();
  if (!hasCrawlIssues(run)) return null;
  const pagesFailed = run.pages_failed ?? 0;
  const filesFailed = run.files_failed ?? 0;
  const hasFailedItems = pagesFailed > 0 || filesFailed > 0;
  return (
    <span className="flex flex-wrap items-center gap-x-1 gap-y-0.5 text-xs">
      {hasFailedItems ? (
        <span className="text-ax-text-secondary">{t("crawl_not_indexed")}</span>
      ) : null}
      {pagesFailed > 0 ? (
        <Button
          variant="ghost"
          size="sm"
          label={t("crawl_view_failed_pages", { count: pagesFailed })}
          onClick={() => onSelect("page")}
        >
          {t("crawl_failed_pages_count", { count: pagesFailed })}
        </Button>
      ) : null}
      {filesFailed > 0 ? (
        <Button
          variant="ghost"
          size="sm"
          label={t("crawl_view_failed_files", { count: filesFailed })}
          onClick={() => onSelect("file")}
        >
          {t("crawl_failed_files_count", { count: filesFailed })}
        </Button>
      ) : null}
      {!hasFailedItems && !isMinorPartial(run) ? (
        <Button
          variant="ghost"
          size="sm"
          label={t("crawl_view_errors")}
          onClick={() => onSelect(null)}
        />
      ) : null}
    </span>
  );
}

type CountColumn = "updated" | "unchanged" | "failed";

/**
 * Pages and files by what happened to them: updated, unchanged, failed. A
 * failed count links to those failures when the caller can show them.
 */
export function CrawlRunCounts({
  run,
  onShowFailures
}: {
  run: CrawlRun;
  onShowFailures?: (kind: CrawlFailureKind) => void;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const columns: { key: CountColumn; label: string }[] = [
    { key: "updated", label: t("crawl_counts_succeeded") },
    { key: "unchanged", label: t("crawl_counts_unchanged") },
    { key: "failed", label: t("crawl_counts_failed") }
  ];
  const rows: ({ kind: CrawlFailureKind; label: string } & Record<
    CountColumn,
    number | null | undefined
  >)[] = [
    {
      kind: "page",
      label: t("crawl_counts_pages"),
      updated: run.pages_crawled,
      unchanged: run.pages_unchanged,
      failed: run.pages_failed
    },
    {
      kind: "file",
      label: t("crawl_counts_files"),
      updated: run.files_downloaded,
      unchanged: run.files_unchanged,
      failed: run.files_failed
    }
  ];

  return (
    <table className="w-full text-xs tabular-nums">
      <caption className="sr-only">{t("crawl_counts_caption")}</caption>
      <thead className="text-ax-text-secondary">
        <tr>
          <td />
          {columns.map((column) => (
            <th key={column.key} scope="col" className="ps-3 pb-1 text-end font-normal">
              {column.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.kind}>
            <th scope="row" className="py-0.5 text-start font-normal">
              {row.label}
            </th>
            {columns.map((column) => {
              const count = row[column.key];
              const failedColumn = column.key === "failed";
              return (
                <td
                  key={column.key}
                  className={cn(
                    "py-0.5 ps-3 text-end",
                    failedColumn && count != null && count > 0 && "text-ax-error font-medium",
                    column.key === "unchanged" && "text-ax-text-secondary"
                  )}
                >
                  {count == null ? (
                    <>
                      <span aria-hidden="true">—</span>
                      <span className="sr-only">{t("crawl_counts_unknown")}</span>
                    </>
                  ) : failedColumn && count > 0 && onShowFailures ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      label={t(
                        row.kind === "page" ? "crawl_view_failed_pages" : "crawl_view_failed_files",
                        { count }
                      )}
                      onClick={() => onShowFailures(row.kind)}
                    >
                      {count.toLocaleString(locale)}
                    </Button>
                  ) : (
                    count.toLocaleString(locale)
                  )}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** A failed load with a way to try again. */
export function CrawlLoadError({
  message,
  loading,
  onRetry
}: {
  message: string;
  loading?: boolean;
  onRetry: () => void;
}) {
  const t = useTranslations();
  return (
    <Banner
      status="error"
      title={message}
      collapsible={false}
      endContent={
        <Button
          size="sm"
          label={t("retry")}
          icon={<RefreshCw aria-hidden="true" />}
          isLoading={loading}
          isInterruptible
          onClick={() => {
            if (!loading) onRetry();
          }}
        />
      }
    />
  );
}
