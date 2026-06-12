"use client";

import { useLocale, useTranslations } from "next-intl";
import { EmptyState } from "@/components/composites/empty-state";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { formatDateTime, formatDuration, formatRelativeTime } from "@/lib/format";
import type { CrawlRun } from "./knowledge";
import { KnowledgeLabel } from "./websites";

const SKIPPED_PREFIX = "skipped";

type Translate = (key: string, params?: Record<string, string>) => string;

function isSkipped(crawl: CrawlRun): boolean {
  return (
    crawl.status === "failed" &&
    (crawl.result_location ?? "").toLowerCase().startsWith(SKIPPED_PREFIX)
  );
}

function hasWarnings(crawl: CrawlRun): boolean {
  return (
    crawl.status === "complete" && ((crawl.pages_failed ?? 0) > 0 || (crawl.files_failed ?? 0) > 0)
  );
}

function statusText(crawl: CrawlRun, t: Translate): string {
  if (isSkipped(crawl)) return t("crawl_skipped");
  switch (crawl.status) {
    case "complete":
      return hasWarnings(crawl) ? t("crawl_completed_with_warnings") : t("complete");
    case "in progress":
      return t("in_progress");
    case "queued":
      return t("queued");
    case "failed":
    case "not found":
      return t("failed");
    default:
      return crawl.status;
  }
}

const FAILURE_REASON_KEYS = [
  "EMPTY_CONTENT",
  "NO_CHUNKS",
  "EMBEDDING_TIMEOUT",
  "EMBEDDING_ERROR",
  "DB_ERROR",
  "NO_EMBEDDING_MODEL",
  "MISSING_PROVIDER"
];

function failureTooltip(crawl: CrawlRun, t: Translate): string | undefined {
  const summary = crawl.failure_summary;
  if (!summary || Object.keys(summary).length === 0) return undefined;
  const lines = Object.entries(summary)
    .map(([reason, count]) => {
      const label = FAILURE_REASON_KEYS.includes(reason) ? t(`failure_reason_${reason}`) : reason;
      return `${label}: ${count}`;
    })
    .join("\n");
  return `${t("failure_reasons_tooltip")}:\n${lines}`;
}

/** Result labels for one crawl run, ported from CrawlResultCell.svelte. */
function CrawlResultCell({ crawl }: { crawl: CrawlRun }) {
  const t = useTranslations();

  if (crawl.status !== "complete") {
    const skipReason = crawl.result_location ?? undefined;
    if (isSkipped(crawl)) {
      return (
        <KnowledgeLabel
          color="gray"
          label={t("crawl_skipped")}
          tooltip={t("crawl_skipped_duplicate")}
        />
      );
    }
    if (crawl.status === "failed" || crawl.status === "not found") {
      return <KnowledgeLabel color="orange" label={t("crawl_failed")} tooltip={skipReason} />;
    }
    if (crawl.status === "queued") return <KnowledgeLabel color="blue" label={t("queued")} />;
    return <KnowledgeLabel color="yellow" label={t("in_progress")} />;
  }

  const pages = crawl.pages_crawled ?? 0;
  const files = crawl.files_downloaded ?? 0;
  const pagesFailed = crawl.pages_failed ?? 0;
  const filesFailed = crawl.files_failed ?? 0;
  const successPages = pages - pagesFailed;
  const successFiles = files - filesFailed;
  const tooltip = failureTooltip(crawl, t);

  return (
    <div className="flex flex-wrap items-center gap-2">
      <KnowledgeLabel
        color="blue"
        label={
          files > 0
            ? t("crawled_pages_and_files", { pages: String(pages), files: String(files) })
            : t("crawled_pages", { count: String(pages) })
        }
      />
      {(successPages > 0 || successFiles > 0) && (
        <KnowledgeLabel
          color="green"
          label={
            successPages > 0 && successFiles > 0
              ? t("pages_and_files_succeeded", {
                  pages: String(successPages),
                  files: String(successFiles)
                })
              : successPages > 0
                ? t("pages_succeeded", { count: String(successPages) })
                : t("files_succeeded", { count: String(successFiles) })
          }
        />
      )}
      {(pagesFailed > 0 || filesFailed > 0) && (
        <KnowledgeLabel
          color="orange"
          label={
            pagesFailed > 0 && filesFailed > 0
              ? t("pages_and_files_failed", {
                  pages: String(pagesFailed),
                  files: String(filesFailed)
                })
              : pagesFailed > 0
                ? t("pages_failed", { count: String(pagesFailed) })
                : t("files_failed", { count: String(filesFailed) })
          }
          tooltip={tooltip}
        />
      )}
    </div>
  );
}

export function CrawlRunsTable({ runs }: { runs: CrawlRun[] }) {
  const t = useTranslations();
  const locale = useLocale();

  if (runs.length === 0) {
    return <EmptyState title={t("this_website_not_crawled_before")} />;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t("started")}</TableHead>
          <TableHead>{t("status")}</TableHead>
          <TableHead>{t("results")}</TableHead>
          <TableHead>{t("duration")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map((run) => (
          <TableRow key={run.id}>
            <TableCell className="font-mono text-sm">{formatDateTime(run.created_at)}</TableCell>
            <TableCell>{statusText(run, t)}</TableCell>
            <TableCell>
              <CrawlResultCell crawl={run} />
            </TableCell>
            <TableCell className="text-muted-foreground text-sm">
              {run.finished_at && run.created_at
                ? formatDuration(run.created_at, run.finished_at)
                : run.created_at
                  ? t("started_time_ago", { timeAgo: formatRelativeTime(run.created_at, locale) })
                  : "—"}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
