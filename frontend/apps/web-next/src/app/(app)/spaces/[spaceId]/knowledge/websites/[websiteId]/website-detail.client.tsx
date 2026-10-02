"use client";

import { Banner } from "@astryxdesign/core/Banner";
import { Button as AstryxButton } from "@astryxdesign/core/Button";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import {
  useMutation,
  useQuery,
  useQueryClient,
  useSuspenseInfiniteQuery,
  useSuspenseQuery
} from "@tanstack/react-query";
import { ChevronLeft, RefreshCw, Square } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { PageHeader } from "@/components/composites/page-header";
import { useClientTimeText } from "@/components/composites/client-time";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { flattenPages } from "@/lib/api/pagination";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import { BlobTable } from "@/features/knowledge/blobs";
import { CrawlRunDetailsDialog } from "@/features/knowledge/crawl-run-details";
import {
  canRequestCrawlStop,
  crawlRunState,
  hasCrawlIssues,
  isActiveCrawlRun,
  isCompletedWithMissingResources
} from "@/features/knowledge/crawl-run-state";
import { CrawlFailureActions } from "@/features/knowledge/crawl-run-ui";
import { CrawlRunsTable, type RunSelection } from "@/features/knowledge/crawl-runs";
import {
  formatWebsiteName,
  websiteBlobPagesQueryOptions,
  websiteCrawlRunsQueryOptions,
  websiteLatestRunQueryOptions,
  websiteQueryOptions,
  type CrawlRun
} from "@/features/knowledge/knowledge";
import { CrawlLimitationsBanner } from "@/features/knowledge/notices";
import { useJobs } from "@/features/jobs/use-jobs";
import { useSpace } from "@/features/spaces/use-space";

const ACTIVE_CRAWL_REFRESH_MS = 2_000;
const IDLE_RUNS_REFRESH_MS = 30_000;

type WebsiteTab = "crawls" | "blobs";

/** The latest run first, then the history without it. */
export function mergeLatestCrawlRun(history: CrawlRun[], latest: CrawlRun | null): CrawlRun[] {
  if (!latest) return history;
  return [latest, ...history.filter((run) => run.id !== latest.id)];
}

/**
 * Starts or stops the website's crawl: "Stoppa" while a run is active
 * ("Stoppar" once a stop is requested), otherwise "Kör igen" (or
 * "Synkronisera nu" before the first run). Both confirm first. The start
 * dialog is controlled by the page so the run details can open it too.
 */
function CrawlRunControls({
  websiteId,
  websiteDisplay,
  activeRun,
  hasHistory,
  startOpen,
  onStartOpenChange
}: {
  websiteId: string;
  websiteDisplay: string;
  activeRun: CrawlRun | undefined;
  hasHistory: boolean;
  startOpen: boolean;
  onStartOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const { trackJob } = useJobs();
  const [stopOpen, setStopOpen] = useState(false);
  const refreshRuns = () =>
    queryClient.invalidateQueries({ queryKey: ["websites", websiteId, "crawl-runs"] });

  const createRun = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/websites/{id}/run/", { params: { path: { id: websiteId } } })
      ),
    onSuccess: () => {
      trackJob();
      void refreshRuns();
      onStartOpenChange(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const stopRun = useMutation({
    mutationFn: (runId: string) =>
      unwrap(
        browserApi.POST("/api/v1/crawl-runs/{id}/cancel/", { params: { path: { id: runId } } })
      ),
    onSuccess: () => {
      toast.success(t("crawl_stopped"));
      void refreshRuns();
      setStopOpen(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const stopRequested = (activeRun && !canRequestCrawlStop(activeRun)) || stopRun.isPending;

  return (
    <>
      {activeRun ? (
        <AstryxButton
          variant="destructive"
          label={stopRequested ? t("stopping_crawl") : t("stop_crawl")}
          icon={<Square className="size-4" aria-hidden="true" />}
          isDisabled={stopRequested && !stopRun.isPending}
          isLoading={stopRun.isPending}
          isInterruptible
          onClick={() => setStopOpen(true)}
        />
      ) : (
        <AstryxButton
          variant="primary"
          label={
            createRun.isPending ? t("starting") : hasHistory ? t("run_crawl_again") : t("sync_now")
          }
          icon={<RefreshCw className="size-4" aria-hidden="true" />}
          isLoading={createRun.isPending}
          isInterruptible
          onClick={() => onStartOpenChange(true)}
        />
      )}
      <ConfirmDialogControlled
        open={startOpen}
        onOpenChange={onStartOpenChange}
        title={t("sync_website")}
        description={t("confirm_sync_website", { websiteName: websiteDisplay })}
        confirmLabel={createRun.isPending ? t("starting") : t("start_crawl")}
        variant="default"
        pending={createRun.isPending}
        onConfirm={() => createRun.mutate()}
      />
      <ConfirmDialogControlled
        open={stopOpen}
        onOpenChange={setStopOpen}
        title={t("stop_crawl_title")}
        description={t("stop_crawl_description", { websiteName: websiteDisplay })}
        confirmLabel={stopRun.isPending ? t("stopping_crawl") : t("stop_crawl")}
        pending={stopRun.isPending}
        onConfirm={() => {
          if (activeRun) stopRun.mutate(activeRun.id);
        }}
      />
    </>
  );
}

/** "Visa fler (x/y)" under a paged list, toasting when a page could not be read. */
function LoadMoreButton({
  label,
  loading,
  onLoad
}: {
  label: string;
  loading: boolean;
  onLoad: () => void;
}) {
  return (
    <div className="flex justify-center">
      <AstryxButton
        label={label}
        isLoading={loading}
        isInterruptible
        onClick={() => {
          if (!loading) onLoad();
        }}
      />
    </div>
  );
}

/** The latest finished run had problems: say so above the content, with links to them. */
function ContentIssuesBanner({
  run,
  onShowFailures
}: {
  run: CrawlRun;
  onShowFailures: (selection: RunSelection) => void;
}) {
  const t = useTranslations();
  const date = useClientTimeText(run.created_at, "date_time");
  const missingOnly = isCompletedWithMissingResources(run);
  return (
    <Banner
      status={missingOnly ? "info" : "warning"}
      title={missingOnly ? t("crawl_content_has_missing") : t("crawl_content_has_failures")}
      description={t("crawl_content_failure_description", { date: date ?? "" })}
      collapsible={false}
      endContent={
        <CrawlFailureActions run={run} onSelect={(kind) => onShowFailures({ run, kind })} />
      }
    />
  );
}

export function WebsiteDetail({
  websiteId,
  integrationRequestFormUrl
}: {
  websiteId: string;
  integrationRequestFormUrl?: string;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const { space, routeId } = useSpace();
  const [tab, setTab] = useState<WebsiteTab>("crawls");
  const [startOpen, setStartOpen] = useState(false);
  const [selection, setSelection] = useState<RunSelection | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const baseId = useId();
  const panelId = `${baseId}-panel`;
  const tabId = (id: WebsiteTab) => `${baseId}-tab-${id}`;

  const { data: website } = useSuspenseQuery(websiteQueryOptions(browserApi, websiteId));
  // The latest run is the source of truth for the crawl's progress: polled
  // quickly while it is active, slowly otherwise (a schedule or another
  // user can start one).
  const { data: latest } = useQuery({
    ...websiteLatestRunQueryOptions(browserApi, websiteId),
    refetchInterval: (query) =>
      query.state.data && isActiveCrawlRun(query.state.data)
        ? ACTIVE_CRAWL_REFRESH_MS
        : IDLE_RUNS_REFRESH_MS
  });
  const runPages = useSuspenseInfiniteQuery(websiteCrawlRunsQueryOptions(browserApi, websiteId));
  const blobPages = useSuspenseInfiniteQuery(websiteBlobPagesQueryOptions(browserApi, websiteId));

  const history = flattenPages<CrawlRun>(runPages.data.pages);
  const runs = mergeLatestCrawlRun(history, latest ?? null);
  const blobs = flattenPages(blobPages.data.pages);
  const runTotal = runPages.data.pages.at(-1)?.total_count ?? history.length;
  const blobTotal = blobPages.data.pages.at(-1)?.total_count ?? blobs.length;

  const latestRun = runs[0];
  const previousLatestRun = useRef<{ id: string; state: string } | null | undefined>(undefined);
  useEffect(() => {
    const current = latestRun ? { id: latestRun.id, state: crawlRunState(latestRun) } : null;
    const previous = previousLatestRun.current;
    previousLatestRun.current = current;
    if (
      previous === undefined ||
      (previous?.id === current?.id && previous?.state === current?.state)
    ) {
      return;
    }
    // The latest run changed: the website, its space and the history show
    // the pre-change snapshot; once the run ends, so does the indexed content.
    void queryClient.invalidateQueries({ queryKey: ["websites", websiteId], exact: true });
    void queryClient.invalidateQueries({ queryKey: ["spaces", routeId], exact: true });
    void queryClient.invalidateQueries({
      queryKey: ["websites", websiteId, "crawl-runs", "pages"]
    });
    if (!latestRun || !isActiveCrawlRun(latestRun)) {
      void queryClient.invalidateQueries({ queryKey: ["websites", websiteId, "info-blobs"] });
    }
  }, [latestRun, queryClient, routeId, websiteId]);

  const readonly = website.space_id !== space.id;
  const activeRun = latestRun && isActiveCrawlRun(latestRun) ? latestRun : undefined;
  const latestCompletedRun = runs.find((run) => !isActiveCrawlRun(run));
  const onRerun = !readonly && !activeRun ? () => setStartOpen(true) : undefined;
  const websiteDisplay = website.name ? `${website.name} (${website.url})` : website.url;

  function loadMore(
    fetchNextPage: () => Promise<{ isError: boolean }>,
    failedKey: "website_crawl_history_load_more_failed" | "website_indexed_content_load_more_failed"
  ) {
    void fetchNextPage().then((result) => {
      if (result.isError) toast.error(t(failedKey));
    });
  }

  function showFailures(next: RunSelection) {
    setSelection(next);
    setDetailsOpen(true);
  }

  return (
    <div className="flex w-full max-w-5xl flex-col gap-6">
      <div className="flex flex-col gap-1">
        <Link
          href={`/spaces/${routeId}/knowledge?tab=websites`}
          className="text-muted-foreground hover:text-foreground flex w-fit items-center gap-1 text-sm"
        >
          <ChevronLeft className="size-4" />
          {t("knowledge")}
        </Link>
        <PageHeader title={formatWebsiteName(website)}>
          {!readonly && (
            <CrawlRunControls
              websiteId={website.id}
              websiteDisplay={websiteDisplay}
              activeRun={activeRun}
              hasHistory={runs.length > 0}
              startOpen={startOpen}
              onStartOpenChange={setStartOpen}
            />
          )}
        </PageHeader>
      </div>
      <div className="flex flex-col gap-4">
        <TabList
          role="tablist"
          aria-label={t("ui_website_tabs_label")}
          value={tab}
          onChange={(value) => setTab(value === "blobs" ? "blobs" : "crawls")}
          hasDivider
        >
          <Tab id={tabId("crawls")} value="crawls" label={t("crawls")} panelId={panelId} />
          <Tab id={tabId("blobs")} value="blobs" label={t("indexed_content")} panelId={panelId} />
        </TabList>
        {/* One panel whose content follows the selected tab, so both tabs'
            aria-controls point at an element that exists. */}
        <div
          role="tabpanel"
          id={panelId}
          aria-labelledby={tabId(tab)}
          className="flex flex-col gap-4"
        >
          {integrationRequestFormUrl ? (
            <CrawlLimitationsBanner integrationRequestFormUrl={integrationRequestFormUrl} />
          ) : null}
          {tab === "crawls" ? (
            <>
              <CrawlRunsTable runs={runs} onRerun={onRerun} />
              {runPages.hasNextPage ? (
                <LoadMoreButton
                  label={t("website_crawl_history_load_more", {
                    current: runs.length,
                    total: runTotal
                  })}
                  loading={runPages.isFetchingNextPage}
                  onLoad={() =>
                    loadMore(runPages.fetchNextPage, "website_crawl_history_load_more_failed")
                  }
                />
              ) : null}
            </>
          ) : (
            <>
              {latestCompletedRun && hasCrawlIssues(latestCompletedRun) ? (
                <ContentIssuesBanner run={latestCompletedRun} onShowFailures={showFailures} />
              ) : null}
              <BlobTable blobs={blobs} canEdit={false} labelledBy={tabId("blobs")} />
              {blobPages.hasNextPage ? (
                <LoadMoreButton
                  label={t("website_indexed_content_load_more", {
                    current: blobs.length,
                    total: blobTotal
                  })}
                  loading={blobPages.isFetchingNextPage}
                  onLoad={() =>
                    loadMore(blobPages.fetchNextPage, "website_indexed_content_load_more_failed")
                  }
                />
              ) : null}
            </>
          )}
        </div>
      </div>
      {selection ? (
        <CrawlRunDetailsDialog
          run={selection.run}
          initialKind={selection.kind}
          isOpen={detailsOpen}
          onOpenChange={setDetailsOpen}
          onRerun={onRerun}
        />
      ) : null}
    </div>
  );
}
