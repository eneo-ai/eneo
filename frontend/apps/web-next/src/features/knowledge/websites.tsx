"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ExternalLink,
  Globe,
  MoreHorizontal,
  Pencil,
  FolderInput,
  RefreshCw,
  Trash2
} from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { EmptyState } from "@/components/composites/empty-state";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { daysSince, formatDateTime, formatRelativeTime } from "@/lib/format";
import { useJobs } from "@/features/jobs/use-jobs";
import { useSpace } from "@/features/spaces/use-space";
import { embeddingModelsInUse, formatWebsiteName, type Website } from "./knowledge";
import { MoveResourceDialog } from "./move-dialog";
import { WebsiteDialog } from "./website-dialog";

const SKIPPED_PREFIX = "skipped duplicate crawl";

export type LabelColor = "green" | "yellow" | "orange" | "blue" | "gray";

const LABEL_CLASSES: Record<LabelColor, string> = {
  green:
    "border-green-200 bg-green-50 text-green-800 dark:border-green-900 dark:bg-green-950 dark:text-green-300",
  yellow:
    "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300",
  orange:
    "border-orange-200 bg-orange-50 text-orange-800 dark:border-orange-900 dark:bg-orange-950 dark:text-orange-300",
  blue: "border-blue-200 bg-blue-50 text-blue-800 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-300",
  gray: "border-border bg-muted text-muted-foreground"
};

export function KnowledgeLabel({
  label,
  color,
  tooltip
}: {
  label: string;
  color: LabelColor;
  tooltip?: string;
}) {
  return (
    <span
      title={tooltip}
      className={`inline-block rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap ${LABEL_CLASSES[color]}`}
    >
      {label}
    </span>
  );
}

/** Latest-crawl status label, ported from WebsiteStatus.svelte. */
function WebsiteStatusLabel({ website }: { website: Website }) {
  const t = useTranslations();
  const locale = useLocale();
  const crawl = website.latest_crawl;
  const skipReason = crawl?.result_location ?? undefined;
  const skipped = skipReason?.toLowerCase().startsWith(SKIPPED_PREFIX) ?? false;
  const pagesFailed = crawl?.pages_failed ?? 0;
  const filesFailed = crawl?.files_failed ?? 0;

  if (!crawl) return <KnowledgeLabel color="gray" label={t("website_not_yet_crawled")} />;

  if (crawl.status === "failed" && skipped) {
    return (
      <KnowledgeLabel
        color="gray"
        label={t("sync_skipped")}
        tooltip={t("crawl_skipped_duplicate")}
      />
    );
  }

  switch (crawl.status) {
    case "complete": {
      const finishedAt = crawl.finished_at ?? crawl.created_at ?? "";
      const syncedOn = t("synced_on", { date: formatDateTime(finishedAt) });
      if (pagesFailed > 0 || filesFailed > 0) {
        const failureText =
          pagesFailed > 0 && filesFailed > 0
            ? t("pages_and_files_failed", {
                pages: String(pagesFailed),
                files: String(filesFailed)
              })
            : pagesFailed > 0
              ? t("pages_failed", { count: String(pagesFailed) })
              : t("files_failed", { count: String(filesFailed) });
        return (
          <KnowledgeLabel
            color="yellow"
            label={t("synced_with_warnings")}
            tooltip={`${syncedOn} - ${failureText}`}
          />
        );
      }
      return (
        <KnowledgeLabel
          color={daysSince(finishedAt) < 10 ? "green" : "yellow"}
          label={t("synced_ago", { timeAgo: formatRelativeTime(finishedAt, locale) })}
          tooltip={syncedOn}
        />
      );
    }
    case "in progress":
      return (
        <KnowledgeLabel
          color="yellow"
          label={t("sync_in_progress")}
          tooltip={t("started_on", { date: formatDateTime(crawl.created_at) })}
        />
      );
    case "queued":
      return <KnowledgeLabel color="blue" label={t("queued")} />;
    default:
      return <KnowledgeLabel color="orange" label={t("sync_failed")} tooltip={skipReason} />;
  }
}

const INTERVAL_DAYS: Record<string, number> = { daily: 1, every_other_day: 2, weekly: 7 };

/** Auto-update interval label with a next-crawl estimate tooltip. */
function WebsiteIntervalLabel({ website }: { website: Website }) {
  const t = useTranslations();
  const locale = useLocale();
  const interval = website.update_interval;

  const labels: Record<string, { label: string; color: LabelColor }> = {
    daily: { color: "green", label: t("every_day") },
    every_other_day: { color: "green", label: t("every_other_day") },
    weekly: { color: "green", label: t("weekly") },
    never: { color: "gray", label: t("never") }
  };
  const item = labels[interval] ?? { color: "orange" as const, label: t("not_found") };

  let tooltip: string | undefined;
  const days = INTERVAL_DAYS[interval];
  if (days) {
    const lastCrawlAt = website.latest_crawl?.finished_at ?? website.latest_crawl?.created_at;
    if (!lastCrawlAt) {
      tooltip = t("next_crawl_after_first_run");
    } else {
      const nextAt = new Date(new Date(lastCrawlAt).getTime() + days * 24 * 60 * 60 * 1000);
      tooltip = t("next_crawl_on", {
        date: `${formatDateTime(nextAt.toISOString())} (${formatRelativeTime(nextAt, locale)})`
      });
    }
  }

  return <KnowledgeLabel color={item.color} label={item.label} tooltip={tooltip} />;
}

function WebsiteActions({ website }: { website: Website }) {
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const queryClient = useQueryClient();
  const [showEdit, setShowEdit] = useState(false);
  const [showMove, setShowMove] = useState(false);
  const [showDelete, setShowDelete] = useState(false);

  const canDelete = website.permissions?.includes("delete") ?? false;
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });

  const deleteWebsite = useMutation({
    mutationFn: () =>
      unwrap(browserApi.DELETE("/api/v1/websites/{id}/", { params: { path: { id: website.id } } })),
    onSuccess: () => {
      invalidate();
      setShowDelete(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const moveWebsite = useMutation({
    mutationFn: (targetSpaceId: string) =>
      unwrap(
        browserApi.POST("/api/v1/websites/{id}/transfer/", {
          params: { path: { id: website.id } },
          body: { target_space_id: targetSpaceId }
        })
      ),
    onSuccess: () => {
      invalidate();
      setShowMove(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const websiteDisplay = website.name ? `${website.name} (${website.url})` : website.url;

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon" aria-label={t("actions")}>
            <MoreHorizontal className="size-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={() => setShowEdit(true)}>
            <Pencil className="size-4" /> {t("edit")}
          </DropdownMenuItem>
          {canDelete && !space.organization && (
            <DropdownMenuItem onSelect={() => setShowMove(true)}>
              <FolderInput className="size-4" /> {t("move")}
            </DropdownMenuItem>
          )}
          {canDelete && (
            <DropdownMenuItem variant="destructive" onSelect={() => setShowDelete(true)}>
              <Trash2 className="size-4" /> {t("delete")}
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      {showEdit && <WebsiteDialog website={website} open={showEdit} onOpenChange={setShowEdit} />}
      <MoveResourceDialog
        open={showMove}
        onOpenChange={setShowMove}
        title={t("move_website")}
        hint={t("move_website_hint")}
        confirmLabel={t("move_website")}
        pending={moveWebsite.isPending}
        onMove={(targetSpaceId) => moveWebsite.mutate(targetSpaceId)}
      />
      <ConfirmDialogControlled
        open={showDelete}
        onOpenChange={setShowDelete}
        title={t("delete_crawl")}
        description={`${t("confirm_delete_crawl_start")} ${websiteDisplay}${t("confirm_delete_crawl_end")}`}
        confirmLabel={deleteWebsite.isPending ? t("deleting") : t("delete")}
        pending={deleteWebsite.isPending}
        onConfirm={() => deleteWebsite.mutate()}
      />
    </>
  );
}

export function WebsitesTab({ canCreate }: { canCreate: boolean }) {
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const queryClient = useQueryClient();
  const { trackJob } = useJobs();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [showCreate, setShowCreate] = useState(false);

  const websites = space.knowledge.websites.items.filter(
    (website) => website.space_id === space.id
  );
  const models = embeddingModelsInUse(websites, space.embedding_models);
  const grouped =
    models.length > 1 ||
    space.embedding_models.length > 1 ||
    models.some((model) => !model.inSpace);

  const bulkRecrawl = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/websites/bulk/run/", {
          body: { website_ids: [...selected] }
        })
      ),
    onSuccess: (result) => {
      if (result.failed > 0) {
        const details = result.errors
          .map((entry) => entry.error)
          .filter(Boolean)
          .join(", ");
        toast.error(
          `${result.queued} ${t("websites").toLowerCase()} queued, ${result.failed} failed${details ? `: ${details}` : ""}`
        );
      }
      setSelected(new Set());
      trackJob();
      void queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
    },
    onError: (error) => toastApiError(error, t)
  });

  function toggle(websiteId: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(websiteId)) next.delete(websiteId);
      else next.add(websiteId);
      return next;
    });
  }

  function toggleAll() {
    setSelected((current) =>
      current.size === websites.length && websites.length > 0
        ? new Set()
        : new Set(websites.map((website) => website.id))
    );
  }

  const toolbar = (
    <div className="flex justify-end gap-2">
      {canCreate && selected.size > 0 && (
        <Button onClick={() => bulkRecrawl.mutate()} disabled={bulkRecrawl.isPending}>
          <RefreshCw className="size-4" />
          {bulkRecrawl.isPending ? t("syncing") : t("sync_selected", { count: selected.size })}
        </Button>
      )}
      {canCreate && selected.size === 0 && (
        <Button onClick={() => setShowCreate(true)}>{t("connect_website")}</Button>
      )}
      {showCreate && <WebsiteDialog open={showCreate} onOpenChange={setShowCreate} />}
    </div>
  );

  if (websites.length === 0) {
    return (
      <div className="flex flex-col gap-4">
        {toolbar}
        <EmptyState title={t("no_results")} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {toolbar}
      {(grouped ? models : [null]).map((model) => {
        const rows = model
          ? websites.filter((website) => website.embedding_model.id === model.id)
          : websites;
        return (
          <div key={model?.id ?? "all"} className="flex flex-col gap-1">
            {model && (
              <h3 className="text-muted-foreground text-sm font-medium">
                {model.name}
                {model.inSpace ? "" : ` (${t("disabled")})`}
              </h3>
            )}
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8">
                    <Checkbox
                      checked={selected.size === websites.length && websites.length > 0}
                      onCheckedChange={toggleAll}
                      aria-label={t("select_all")}
                    />
                  </TableHead>
                  <TableHead>{t("website")}</TableHead>
                  <TableHead>{t("link")}</TableHead>
                  <TableHead>{t("status")}</TableHead>
                  <TableHead>{t("auto_updates")}</TableHead>
                  <TableHead className="w-16" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((website) => (
                  <TableRow key={website.id}>
                    <TableCell>
                      <Checkbox
                        checked={selected.has(website.id)}
                        onCheckedChange={() => toggle(website.id)}
                        aria-label={formatWebsiteName(website)}
                      />
                    </TableCell>
                    <TableCell>
                      <Link
                        href={`/spaces/${routeId}/knowledge/websites/${website.id}`}
                        className="flex max-w-64 items-center gap-2 font-medium hover:underline"
                        title={website.url}
                      >
                        <Globe className="text-muted-foreground size-4 shrink-0" />
                        <span className="truncate">{formatWebsiteName(website)}</span>
                      </Link>
                    </TableCell>
                    <TableCell>
                      <a
                        href={website.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-sm"
                      >
                        {t("go_to_website")}
                        <ExternalLink className="size-3.5" />
                      </a>
                    </TableCell>
                    <TableCell>
                      <WebsiteStatusLabel website={website} />
                    </TableCell>
                    <TableCell>
                      <WebsiteIntervalLabel website={website} />
                    </TableCell>
                    <TableCell className="text-right">
                      <WebsiteActions website={website} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        );
      })}
    </div>
  );
}
