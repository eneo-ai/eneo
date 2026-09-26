"use client";

import { Button as AstryxButton } from "@astryxdesign/core/Button";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { useMutation, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { ChevronLeft, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { PageHeader } from "@/components/composites/page-header";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { BlobTable } from "@/features/knowledge/blobs";
import { CrawlRunsTable } from "@/features/knowledge/crawl-runs";
import {
  formatWebsiteName,
  websiteBlobsQueryOptions,
  websiteCrawlRunsQueryOptions,
  websiteQueryOptions
} from "@/features/knowledge/knowledge";
import { CrawlLimitationsBanner } from "@/features/knowledge/notices";
import { useJobs } from "@/features/jobs/use-jobs";
import { useSpace } from "@/features/spaces/use-space";

const RUNS_REFRESH_MS = 30_000;

type WebsiteTab = "crawls" | "blobs";

function SyncNowButton({
  websiteId,
  websiteDisplay,
  disabled
}: {
  websiteId: string;
  websiteDisplay: string;
  disabled: boolean;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const { trackJob } = useJobs();
  const [open, setOpen] = useState(false);
  const reasonId = useId();

  const createRun = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/websites/{id}/run/", { params: { path: { id: websiteId } } })
      ),
    onSuccess: () => {
      trackJob();
      void queryClient.invalidateQueries({ queryKey: ["websites", websiteId] });
      setOpen(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <>
      {/* While a crawl runs the button is disabled; the reason is visible text,
          not a tooltip, so keyboard and touch users get it too. */}
      <div className="flex flex-col items-end gap-1">
        <AstryxButton
          variant="primary"
          label={t("sync_now")}
          icon={<RefreshCw className="size-4" aria-hidden="true" />}
          isDisabled={disabled}
          aria-describedby={disabled ? reasonId : undefined}
          onClick={() => setOpen(true)}
        />
        {disabled ? (
          <p id={reasonId} className="text-ax-text-secondary text-sm">
            {t("cant_sync_while_crawl_running")}
          </p>
        ) : null}
      </div>
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("sync_website")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("confirm_sync_website", { websiteName: websiteDisplay })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("cancel")}</AlertDialogCancel>
            {/* Busy, it stays enabled so it keeps focus; a second press is ignored. */}
            <Button
              aria-busy={createRun.isPending || undefined}
              onClick={() => {
                if (!createRun.isPending) createRun.mutate();
              }}
            >
              {createRun.isPending ? t("starting") : t("start_crawl")}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
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
  const { space, routeId } = useSpace();
  const [tab, setTab] = useState<WebsiteTab>("crawls");
  const baseId = useId();
  const panelId = `${baseId}-panel`;
  const tabId = (id: WebsiteTab) => `${baseId}-tab-${id}`;

  const { data: website } = useSuspenseQuery(websiteQueryOptions(browserApi, websiteId));
  const { data: runs } = useSuspenseQuery({
    ...websiteCrawlRunsQueryOptions(browserApi, websiteId),
    refetchInterval: RUNS_REFRESH_MS
  });
  const { data: blobs } = useSuspenseQuery(websiteBlobsQueryOptions(browserApi, websiteId));

  const readonly = website.space_id !== space.id;
  const crawlActive = runs.some((run) => run.status === "in progress" || run.status === "queued");
  const websiteDisplay = website.name ? `${website.name} (${website.url})` : website.url;

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
            <SyncNowButton
              websiteId={website.id}
              websiteDisplay={websiteDisplay}
              disabled={crawlActive}
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
            <CrawlRunsTable runs={runs} />
          ) : (
            <BlobTable blobs={blobs} canEdit={false} labelledBy={tabId("blobs")} />
          )}
        </div>
      </div>
    </div>
  );
}
