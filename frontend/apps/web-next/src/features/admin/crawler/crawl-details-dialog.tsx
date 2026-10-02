"use client";

import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { Pagination } from "@astryxdesign/core/Pagination";
import { pixel, proportional, type TableColumn } from "@astryxdesign/core/Table";
import { Table } from "@/components/astryx/table";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useId, useState } from "react";
import { ClientTime, useClientTimeText } from "@/components/composites/client-time";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { LoadingState } from "@/components/composites/loading-state";
import { browserApi } from "@/lib/api/browser";
import { getErrorMessage, unwrap } from "@/lib/api/errors";
import { formatBytes } from "@/lib/format";
import { toastApiError } from "@/lib/api/toast";
import { CrawlRunDetailsContent } from "@/features/knowledge/crawl-run-details";
import { canRequestCrawlStop, isActiveCrawlRun } from "@/features/knowledge/crawl-run-state";
import {
  CrawlLoadError,
  CrawlRunCounts,
  CrawlRunStatusLabel
} from "@/features/knowledge/crawl-run-ui";
import type { CrawlRun } from "@/features/knowledge/knowledge";
import {
  crawlerDetailsQueryOptions,
  crawlerFailuresQueryOptions,
  crawlerWebsiteMatchesQueryOptions,
  crawlerWebsiteRunsQueryOptions,
  type CrawlerDetails,
  type CrawlerRelatedWebsite
} from "./crawler";
import { intervalLabelKey } from "./schedule-format";

type DetailsView = "details" | "source" | "history" | "matches";

const RETRY_OUTCOMES = new Set(["failed", "interrupted", "partial"]);

/** Previous/next over a cursor-paged list: the stack of cursors seen so far. */
function useCursorStack() {
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  return {
    cursor: cursors.at(-1) ?? null,
    page: cursors.length,
    reset: () => setCursors([null]),
    go: (page: number, nextCursor: string | null | undefined) =>
      setCursors((current) =>
        page < current.length
          ? current.slice(0, page)
          : nextCursor
            ? [...current, nextCursor]
            : current
      )
  };
}

/** A run's requested time as a button that selects that run. */
function RunLink({ run, onSelect }: { run: CrawlRun; onSelect: () => void }) {
  const t = useTranslations();
  const date = useClientTimeText(run.created_at, "date_time");
  return (
    <Button
      variant="ghost"
      size="sm"
      label={t("admin_crawler_select_run", { date: date ?? "—" })}
      onClick={onSelect}
    >
      {run.created_at ? <ClientTime value={run.created_at} format="date_time" /> : "—"}
    </Button>
  );
}

/** The website's crawl history from the admin endpoint, ten runs a page. */
function HistoryTab({
  websiteId,
  onSelect
}: {
  websiteId: string;
  onSelect: (runId: string) => void;
}) {
  const t = useTranslations();
  const stack = useCursorStack();
  const history = useQuery(crawlerWebsiteRunsQueryOptions(browserApi, websiteId, stack.cursor));
  const runs = history.data?.items ?? [];

  const columns: TableColumn<CrawlRun>[] = [
    {
      key: "requested",
      header: t("admin_crawler_requested"),
      width: proportional(2),
      renderCell: (run) => <RunLink run={run} onSelect={() => onSelect(run.id)} />
    },
    {
      key: "status",
      header: t("status"),
      width: proportional(2),
      renderCell: (run) => <CrawlRunStatusLabel run={run} />
    },
    {
      key: "result",
      header: t("admin_crawler_result"),
      width: pixel(260),
      renderCell: (run) => <CrawlRunCounts run={run} />
    }
  ];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-medium">{t("history")}</h3>
        <Button
          size="sm"
          label={t("admin_crawler_refresh_history")}
          icon={<RefreshCw aria-hidden="true" />}
          isLoading={history.isFetching}
          isInterruptible
          onClick={() => {
            if (!history.isFetching) void history.refetch();
          }}
        >
          {t("refresh")}
        </Button>
      </div>
      {history.isError ? (
        <CrawlLoadError
          message={t("admin_crawler_history_error")}
          loading={history.isFetching}
          onRetry={() => void history.refetch()}
        />
      ) : history.isPending ? (
        <LoadingState rows={3} />
      ) : runs.length === 0 ? (
        <p className="text-ax-text-secondary py-6 text-sm">{t("admin_crawler_history_empty")}</p>
      ) : (
        <Table data={runs} columns={columns} idKey="id" aria-label={t("history")} />
      )}
      {history.data && (stack.page > 1 || history.data.next_cursor) ? (
        <Pagination
          variant="none"
          size="sm"
          page={stack.page}
          hasMore={Boolean(history.data.next_cursor)}
          isDisabled={history.isFetching}
          onChange={(page) => stack.go(page, history.data?.next_cursor)}
          label={t("history")}
        />
      ) : null}
    </div>
  );
}

/** Other sources registered with the exact same address, ten a page. */
function MatchesTab({
  websiteId,
  onSelect
}: {
  websiteId: string;
  onSelect: (runId: string) => void;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const stack = useCursorStack();
  const matches = useQuery(crawlerWebsiteMatchesQueryOptions(browserApi, websiteId, stack.cursor));
  const items: CrawlerRelatedWebsite[] = matches.data?.items ?? [];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <p className="text-ax-text-secondary max-w-prose text-sm">
          {t("admin_crawler_same_address_description")}
        </p>
        <Button
          size="sm"
          label={t("admin_crawler_refresh_matches")}
          icon={<RefreshCw aria-hidden="true" />}
          isLoading={matches.isFetching}
          isInterruptible
          onClick={() => {
            if (!matches.isFetching) void matches.refetch();
          }}
        >
          {t("refresh")}
        </Button>
      </div>
      {matches.isError ? (
        <CrawlLoadError
          message={t("admin_crawler_matches_error")}
          loading={matches.isFetching}
          onRetry={() => void matches.refetch()}
        />
      ) : matches.isPending ? (
        <LoadingState rows={2} />
      ) : items.length === 0 ? (
        <p className="text-ax-text-secondary py-6 text-sm">
          {t("admin_crawler_same_address_empty")}
        </p>
      ) : (
        <ul className="divide-ax-border flex flex-col divide-y">
          {items.map((source) => (
            <li
              key={source.website_id}
              className="flex min-w-0 flex-wrap items-start justify-between gap-3 py-3"
            >
              <MatchItem source={source} onSelect={onSelect} />
              <span className="text-ax-text-secondary text-sm tabular-nums">
                {formatBytes(source.indexed_size, locale)}
              </span>
            </li>
          ))}
        </ul>
      )}
      {matches.data && (stack.page > 1 || matches.data.next_cursor) ? (
        <Pagination
          variant="none"
          size="sm"
          page={stack.page}
          hasMore={Boolean(matches.data.next_cursor)}
          isDisabled={matches.isFetching}
          onChange={(page) => stack.go(page, matches.data?.next_cursor)}
          label={t("admin_crawler_same_address")}
        />
      ) : null}
    </div>
  );
}

function MatchItem({
  source,
  onSelect
}: {
  source: CrawlerRelatedWebsite;
  onSelect: (runId: string) => void;
}) {
  const t = useTranslations();
  const lastIndexed = useClientTimeText(source.last_indexed_at, "date_time");
  const name = source.website_name || source.website_url;
  return (
    <span className="flex min-w-0 flex-1 flex-col items-start gap-1">
      {source.latest_run_id ? (
        <Button
          variant="ghost"
          size="sm"
          label={name}
          onClick={() => source.latest_run_id && onSelect(source.latest_run_id)}
        >
          <span className="break-all whitespace-normal">{name}</span>
        </Button>
      ) : (
        <span className="break-all">{name}</span>
      )}
      <span className="text-ax-text-secondary text-sm break-words">
        {source.space_name ?? t("admin_crawler_not_recorded")}
      </span>
      <span className="text-ax-text-secondary text-xs">
        {source.latest_run_id
          ? `${t("admin_crawler_last_indexed")}: ${lastIndexed ?? "—"}`
          : t("admin_crawler_no_run")}
      </span>
    </span>
  );
}

/** Who owns the source and what it has stored; the source as a whole, not the run. */
function SourceTab({
  details,
  refreshing,
  onRefresh,
  onSelect
}: {
  details: CrawlerDetails;
  refreshing: boolean;
  onRefresh: () => void;
  onSelect: (runId: string) => void;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const retryAt = useClientTimeText(details.next_retry_at, "date_time");
  const otherActive = details.active_run?.id !== details.run.id ? details.active_run : null;
  const latest = details.latest_run;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start justify-between gap-3">
        <p className="text-ax-text-secondary max-w-prose text-sm">
          {t("admin_crawler_source_description")}
        </p>
        <Button
          size="sm"
          label={t("admin_crawler_refresh_source")}
          icon={<RefreshCw aria-hidden="true" />}
          isLoading={refreshing}
          isInterruptible
          onClick={() => {
            if (!refreshing) onRefresh();
          }}
        >
          {t("refresh")}
        </Button>
      </div>
      <MetadataList columns="multi">
        <MetadataListItem label={t("admin_crawler_owning_space")}>
          {details.space_name ?? t("admin_crawler_not_recorded")}
        </MetadataListItem>
        <MetadataListItem label={t("admin_crawler_source_owner")}>
          <span className="flex flex-col">
            <span className="break-words">{details.owner.username || details.owner.email}</span>
            {details.owner.username ? (
              <span className="text-ax-text-secondary text-xs break-all">
                {details.owner.email}
              </span>
            ) : null}
          </span>
        </MetadataListItem>
        <MetadataListItem label={t("admin_crawler_schedule")}>
          {t(intervalLabelKey(details.update_interval))}
        </MetadataListItem>
        <MetadataListItem label={t("admin_crawler_stored_documents")}>
          <span className="tabular-nums">{details.stored_resources}</span>
        </MetadataListItem>
        <MetadataListItem label={t("admin_crawler_indexed_storage")}>
          <span className="tabular-nums">{formatBytes(details.indexed_size, locale)}</span>
        </MetadataListItem>
        <MetadataListItem label={t("admin_crawler_last_indexed")}>
          {details.last_indexed_at ? (
            <ClientTime value={details.last_indexed_at} format="date_time" />
          ) : (
            "—"
          )}
        </MetadataListItem>
        <MetadataListItem label={t("admin_crawler_latest_crawl")}>
          {latest?.created_at ? <ClientTime value={latest.created_at} format="date_time" /> : "—"}
        </MetadataListItem>
      </MetadataList>
      <p className="text-ax-text-secondary text-xs">{t("admin_crawler_storage_help")}</p>
      {details.consecutive_failures > 0 ? (
        <p className="text-ax-text-secondary text-sm">
          {t("admin_crawler_consecutive_failures", { count: details.consecutive_failures })}
        </p>
      ) : null}
      {details.next_retry_at ? (
        <p className="text-ax-text-secondary text-sm">
          {t("admin_crawler_retry_after", { time: retryAt ?? "—" })}
        </p>
      ) : null}
      {latest && latest.id !== details.run.id && !otherActive ? (
        <div>
          <Button label={t("admin_crawler_view_latest")} onClick={() => onSelect(latest.id)} />
        </div>
      ) : null}
    </div>
  );
}

/**
 * One crawl run as an administrator sees it: the run's details and
 * failures, the source's ownership and storage, the website's history and
 * other sources with the same address, with "run again" / "stop" for the
 * run. Selecting another run (`onSelect`) swaps the dialog's content.
 */
export function CrawlDetailsDialog({
  runId,
  isOpen,
  onOpenChange,
  onSelect,
  onChange
}: {
  runId: string;
  isOpen: boolean;
  onOpenChange: (isOpen: boolean) => void;
  /** Show another run in this dialog. */
  onSelect: (runId: string) => void;
  /** A run was started or stopped: the overview should refresh. */
  onChange: () => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const baseId = useId();
  const [view, setView] = useState<DetailsView>("details");
  const [confirmation, setConfirmation] = useState<"start" | "cancel" | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const details = useQuery({ ...crawlerDetailsQueryOptions(browserApi, runId), enabled: isOpen });
  const data = details.data;
  const requestedAt = useClientTimeText(data?.run.created_at, "date_time");
  const startedAt = useClientTimeText(data?.started_at, "date_time");

  const act = useMutation({
    mutationFn: (operation: "start" | "cancel") =>
      operation === "start"
        ? unwrap(
            browserApi.POST("/api/v1/admin/crawler/websites/{id}/run/", {
              params: { path: { id: data!.website_id } }
            })
          )
        : unwrap(
            browserApi.POST("/api/v1/admin/crawler/runs/{id}/cancel/", {
              params: { path: { id: runId } }
            })
          ),
    onSuccess: (result) => {
      onChange();
      setConfirmation(null);
      setView("details");
      void queryClient.invalidateQueries({ queryKey: ["admin", "crawler"] });
      if (result.id !== runId) onSelect(result.id);
    },
    onError: (error) => {
      // The confirmation stays open so the user can retry or cancel; the
      // reason is toasted (it stays until closed) and shown in the footer.
      toastApiError(error, t);
      setActionError(getErrorMessage(error, t));
    }
  });

  const websiteName = data?.website_name || data?.website_url || t("website");
  const otherActive = data && data.active_run?.id !== runId ? data.active_run : null;
  const retry = RETRY_OUTCOMES.has(data?.run.outcome ?? "");
  const startLabel = retry ? t("admin_crawler_retry_crawl") : t("run_crawl_again");
  const busy = act.isPending;
  const panelId = `${baseId}-panel`;
  const tabId = (id: DetailsView) => `${baseId}-tab-${id}`;

  // While a start or stop runs the dialog stays on this run: a selection
  // made meanwhile is ignored rather than the links being disabled.
  function selectRun(nextId: string) {
    if (busy) return;
    setView("details");
    onSelect(nextId);
  }

  const views: { id: DetailsView; label: string }[] = [
    { id: "details", label: t("details") },
    { id: "source", label: t("admin_crawler_source") },
    { id: "history", label: t("history") },
    { id: "matches", label: t("admin_crawler_same_address") }
  ];

  return (
    <>
      <Dialog isOpen={isOpen} onOpenChange={onOpenChange} width={760} maxHeight="90dvh">
        <Layout
          height="auto"
          header={
            <DialogHeader
              title={websiteName}
              subtitle={data?.website_url ?? t("crawl_details_description")}
              onOpenChange={onOpenChange}
            />
          }
          content={
            <LayoutContent>
              {details.isError ? (
                <CrawlLoadError
                  message={t("admin_crawler_details_error")}
                  loading={details.isFetching}
                  onRetry={() => void details.refetch()}
                />
              ) : !data ? (
                <LoadingState rows={4} />
              ) : (
                <div className="flex flex-col gap-3">
                  <TabList
                    role="tablist"
                    aria-label={t("crawl_details_description")}
                    value={view}
                    onChange={(value) => setView(value as DetailsView)}
                    hasDivider
                  >
                    {views.map((item) => (
                      <Tab
                        key={item.id}
                        id={tabId(item.id)}
                        value={item.id}
                        label={item.label}
                        panelId={panelId}
                      />
                    ))}
                  </TabList>
                  <div role="tabpanel" id={panelId} aria-labelledby={tabId(view)}>
                    {view === "details" ? (
                      <div className="flex flex-col gap-4">
                        <div>
                          <h3 className="font-medium">
                            {t("crawl_details_title", { date: requestedAt ?? "" })}
                          </h3>
                          {data.started_at ? (
                            <p className="text-ax-text-secondary mt-1 text-xs">
                              {t("admin_crawler_started", { time: startedAt ?? "—" })}
                            </p>
                          ) : null}
                        </div>
                        <p className="text-ax-text-secondary text-sm">
                          {t("admin_crawler_initiated_by")}:{" "}
                          {data.run.origin === "scheduled"
                            ? t("crawl_origin_scheduled")
                            : data.initiated_by?.username ||
                              data.initiated_by?.email ||
                              t("admin_crawler_not_recorded")}
                        </p>
                        <CrawlRunDetailsContent
                          key={runId}
                          run={data.run}
                          failuresQuery={(id, kind) =>
                            crawlerFailuresQueryOptions(browserApi, id, kind)
                          }
                          onRefresh={() => details.refetch()}
                          onRunUpdate={(run) =>
                            queryClient.setQueryData(
                              crawlerDetailsQueryOptions(browserApi, runId).queryKey,
                              (current) => (current ? { ...current, run } : current)
                            )
                          }
                        />
                      </div>
                    ) : view === "source" ? (
                      <SourceTab
                        details={data}
                        refreshing={details.isFetching}
                        onRefresh={() => void details.refetch()}
                        onSelect={selectRun}
                      />
                    ) : view === "history" ? (
                      <HistoryTab websiteId={data.website_id} onSelect={selectRun} />
                    ) : (
                      <MatchesTab websiteId={data.website_id} onSelect={selectRun} />
                    )}
                  </div>
                </div>
              )}
            </LayoutContent>
          }
          footer={
            data ? (
              <LayoutFooter>
                <div className="flex flex-col gap-3">
                  {actionError && !confirmation ? (
                    <p className="text-ax-error text-sm">{actionError}</p>
                  ) : null}
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex min-w-0 flex-col items-start gap-1">
                      <p className="text-ax-text-secondary text-xs">
                        {t("admin_crawler_selected_run", { date: requestedAt ?? "—" })}
                      </p>
                      <CrawlRunStatusLabel run={data.run} />
                    </div>
                    {otherActive ? (
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-ax-text-secondary text-sm">
                          {t("admin_crawler_newer_active")}
                        </p>
                        <Button
                          label={t("admin_crawler_view_active")}
                          onClick={() => selectRun(otherActive.id)}
                        />
                      </div>
                    ) : isActiveCrawlRun(data.run) ? (
                      <Button
                        variant="destructive"
                        label={
                          canRequestCrawlStop(data.run) ? t("stop_crawl") : t("stopping_crawl")
                        }
                        isDisabled={!canRequestCrawlStop(data.run)}
                        isLoading={busy}
                        isInterruptible
                        onClick={() => {
                          if (busy) return;
                          setActionError(null);
                          setConfirmation("cancel");
                        }}
                      />
                    ) : (
                      <Button
                        variant="primary"
                        label={busy ? t("starting") : startLabel}
                        isLoading={busy}
                        isInterruptible
                        onClick={() => {
                          if (busy) return;
                          setActionError(null);
                          setConfirmation("start");
                        }}
                      />
                    )}
                  </div>
                </div>
              </LayoutFooter>
            ) : undefined
          }
        />
      </Dialog>
      <ConfirmDialogControlled
        open={confirmation !== null && isOpen}
        onOpenChange={(open) => {
          if (!open) setConfirmation(null);
        }}
        title={confirmation === "cancel" ? t("stop_crawl_title") : startLabel}
        description={
          confirmation === "cancel"
            ? t("stop_crawl_description", { websiteName })
            : t("admin_crawler_rerun_description", { websiteName })
        }
        confirmLabel={
          confirmation === "cancel"
            ? busy
              ? t("stopping_crawl")
              : t("stop_crawl")
            : busy
              ? t("starting")
              : startLabel
        }
        variant={confirmation === "cancel" ? "destructive" : "default"}
        pending={busy}
        onConfirm={() => {
          if (confirmation && data) act.mutate(confirmation);
        }}
      />
    </>
  );
}
