"use client";

import { useMutation, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { ChevronLeft, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
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
import { useJobs } from "@/features/jobs/use-jobs";
import { useSpace } from "@/features/spaces/use-space";

const RUNS_REFRESH_MS = 30_000;

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
      <Button
        disabled={disabled}
        onClick={() => setOpen(true)}
        title={disabled ? t("cant_sync_while_crawl_running") : undefined}
      >
        <RefreshCw className="size-4" />
        {t("sync_now")}
      </Button>
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
            <Button disabled={createRun.isPending} onClick={() => createRun.mutate()}>
              {createRun.isPending ? t("starting") : t("start_crawl")}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

export function WebsiteDetail({ websiteId }: { websiteId: string }) {
  const t = useTranslations();
  const { space, routeId } = useSpace();

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
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
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
      <Tabs defaultValue="crawls">
        <TabsList>
          <TabsTrigger value="crawls">{t("crawls")}</TabsTrigger>
          <TabsTrigger value="blobs">{t("indexed_content")}</TabsTrigger>
        </TabsList>
        <TabsContent value="crawls" className="pt-4">
          <CrawlRunsTable runs={runs} />
        </TabsContent>
        <TabsContent value="blobs" className="pt-4">
          <BlobTable blobs={blobs} canEdit={false} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
