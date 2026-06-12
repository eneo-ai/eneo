"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from "@/components/ui/alert-dialog";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { formatDateTime } from "@/lib/format";
import { useSpace } from "@/features/spaces/use-space";
import { EmbeddingModelSelect } from "./embedding-model-select";
import type { Website } from "./knowledge";

type CrawlType = Website["crawl_type"];
type UpdateInterval = Website["update_interval"];

type ExistingWebsite = {
  space_name: string;
  last_crawled_at: string | null;
  update_interval: string;
  pages_crawled: number | null;
  pages_failed: number | null;
  files_downloaded: number | null;
  files_failed: number | null;
  crawl_status: string | null;
};

function crawlResultSummary(
  existing: ExistingWebsite,
  t: (key: string, params?: Record<string, string>) => string
): { text: string; hasFailures: boolean } | null {
  if (existing.crawl_status === "in progress" || existing.crawl_status === "queued") {
    return { text: t("website_crawl_in_progress"), hasFailures: false };
  }
  const totalPages = existing.pages_crawled ?? 0;
  const pagesFailed = existing.pages_failed ?? 0;
  const totalFiles = existing.files_downloaded ?? 0;
  const filesFailed = existing.files_failed ?? 0;
  if (totalPages === 0 && totalFiles === 0) return null;

  if (totalFiles === 0) {
    if (pagesFailed === 0) {
      return {
        text: t("website_all_pages_indexed", { count: String(totalPages) }),
        hasFailures: false
      };
    }
    return {
      text: t("website_pages_indexed", {
        success: String(totalPages - pagesFailed),
        total: String(totalPages)
      }),
      hasFailures: true
    };
  }
  return {
    text: t("website_pages_indexed_with_files", {
      successPages: String(totalPages - pagesFailed),
      totalPages: String(totalPages),
      successFiles: String(totalFiles - filesFailed),
      totalFiles: String(totalFiles)
    }),
    hasFailures: pagesFailed > 0 || filesFailed > 0
  };
}

function intervalLabel(interval: string, t: (key: string) => string): string {
  switch (interval) {
    case "daily":
      return t("every_day");
    case "every_other_day":
      return t("every_other_day");
    case "weekly":
      return t("every_week");
    default:
      return t("never");
  }
}

/**
 * Create / edit a website crawl. On create (outside the org space) the URL is
 * first checked against the organization space; a warning dialog offers
 * "create anyway" when it already exists there.
 */
export function WebsiteDialog({
  website,
  open,
  onOpenChange
}: {
  website?: Website;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const queryClient = useQueryClient();

  const [url, setUrl] = useState(website?.url ?? "");
  const [name, setName] = useState(website?.name ?? "");
  const [crawlType, setCrawlType] = useState<CrawlType>(website?.crawl_type ?? "crawl");
  const [updateInterval, setUpdateInterval] = useState<UpdateInterval>(
    website?.update_interval ?? "never"
  );
  const [downloadFiles, setDownloadFiles] = useState(website?.download_files ?? false);
  const [modelId, setModelId] = useState<string | undefined>(space.embedding_models[0]?.id);
  const [httpAuthEnabled, setHttpAuthEnabled] = useState(website?.requires_http_auth ?? false);
  const [httpAuthUsername, setHttpAuthUsername] = useState("");
  const [httpAuthPassword, setHttpAuthPassword] = useState("");
  const [existingOnOrg, setExistingOnOrg] = useState<ExistingWebsite | null>(null);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
    void queryClient.invalidateQueries({ queryKey: ["websites"] });
  };

  const save = useMutation({
    mutationFn: async () => {
      if (website) {
        const body: Record<string, unknown> = {
          url,
          name: name === "" ? null : name,
          crawl_type: crawlType,
          update_interval: updateInterval,
          download_files: downloadFiles
        };
        if (httpAuthEnabled && httpAuthUsername) {
          body.http_auth_username = httpAuthUsername;
          if (httpAuthPassword) body.http_auth_password = httpAuthPassword;
        } else if (!httpAuthEnabled && website.requires_http_auth) {
          body.http_auth_username = null;
          body.http_auth_password = null;
        }
        return unwrap(
          browserApi.POST("/api/v1/websites/{id}/", {
            params: { path: { id: website.id } },
            body
          })
        );
      }
      const body: Record<string, unknown> = {
        url,
        name: name === "" ? null : name,
        crawl_type: crawlType,
        update_interval: updateInterval,
        download_files: downloadFiles,
        embedding_model: modelId ? { id: modelId } : undefined
      };
      if (httpAuthEnabled && httpAuthUsername && httpAuthPassword) {
        body.http_auth_username = httpAuthUsername;
        body.http_auth_password = httpAuthPassword;
      }
      return unwrap(
        browserApi.POST("/api/v1/spaces/{id}/knowledge/websites/", {
          params: { path: { id: space.id } },
          body: body as { url: string }
        })
      );
    },
    onSuccess: () => {
      invalidate();
      setExistingOnOrg(null);
      onOpenChange(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const checkUrl = useMutation({
    mutationFn: () =>
      unwrap(browserApi.GET("/api/v1/websites/check-url/", { params: { query: { url } } })),
    onSuccess: (existing) => {
      if (existing) setExistingOnOrg(existing as unknown as ExistingWebsite);
      else save.mutate();
    },
    // The duplicate check is advisory: create anyway when it fails.
    onError: () => save.mutate()
  });

  function submit() {
    if (website || space.organization) save.mutate();
    else checkUrl.mutate();
  }

  const pending = save.isPending || checkUrl.isPending;
  const noModels = !website && space.embedding_models.length === 0;
  const crawlResult = existingOnOrg ? crawlResultSummary(existingOnOrg, t) : null;

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {website ? t("edit_website_integration") : t("create_website_integration")}
            </DialogTitle>
          </DialogHeader>
          <form
            className="flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (url) submit();
            }}
          >
            {noModels && (
              <p className="border-destructive/50 text-destructive rounded-md border px-3 py-2 text-sm">
                <span className="font-bold">{t("warning")}: </span>
                {t("warning_no_embedding_models")}
              </p>
            )}
            <div className="flex flex-col gap-2">
              <Label htmlFor="website-url">{t("url_required")}</Label>
              <Input
                id="website-url"
                type="url"
                required
                value={url}
                placeholder={
                  crawlType === "sitemap"
                    ? "https://example.com/sitemap.xml"
                    : "https://example.com"
                }
                onChange={(event) => setUrl(event.target.value)}
              />
              <p className="text-muted-foreground text-sm">
                {crawlType === "sitemap" ? t("full_url_sitemap") : t("url_description")}
              </p>
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="website-name">{t("display_name")}</Label>
              <Input
                id="website-name"
                value={name}
                placeholder={url.split("//")[1] ?? url}
                onChange={(event) => setName(event.target.value)}
              />
              <p className="text-muted-foreground text-sm">{t("display_name_optional")}</p>
            </div>

            <div className="flex items-center justify-between gap-4">
              <Label htmlFor="website-http-auth">{t("requires_http_auth")}</Label>
              <Switch
                id="website-http-auth"
                checked={httpAuthEnabled}
                onCheckedChange={(checked) => {
                  setHttpAuthEnabled(checked);
                  if (!checked) {
                    setHttpAuthUsername("");
                    setHttpAuthPassword("");
                  }
                }}
              />
            </div>
            {httpAuthEnabled && (
              <div className="flex flex-col gap-4 rounded-md border p-3">
                <p className="text-muted-foreground text-sm">
                  <span className="font-medium">{t("security_note")} </span>
                  {t("credentials_encrypted_securely")}
                </p>
                {website?.requires_http_auth && (
                  <p className="text-sm text-green-700 dark:text-green-500">
                    {t("authentication_configured")}
                  </p>
                )}
                <div className="flex flex-col gap-2">
                  <Label htmlFor="http-auth-username">{t("username")}</Label>
                  <Input
                    id="http-auth-username"
                    value={httpAuthUsername}
                    autoComplete="username"
                    onChange={(event) => setHttpAuthUsername(event.target.value)}
                  />
                </div>
                <div className="flex flex-col gap-2">
                  <Label htmlFor="http-auth-password">{t("password")}</Label>
                  <Input
                    id="http-auth-password"
                    type="password"
                    value={httpAuthPassword}
                    autoComplete="current-password"
                    onChange={(event) => setHttpAuthPassword(event.target.value)}
                  />
                  {website?.requires_http_auth && (
                    <p className="text-muted-foreground text-sm">
                      {t("leave_blank_keep_password")}
                    </p>
                  )}
                </div>
              </div>
            )}

            <div className="flex gap-4">
              <div className="flex flex-1 flex-col gap-2">
                <Label>{t("crawl_type")}</Label>
                <Select
                  value={crawlType}
                  onValueChange={(value) => {
                    setCrawlType(value as CrawlType);
                    if (value === "sitemap") setDownloadFiles(false);
                  }}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="crawl">{t("basic_crawl")}</SelectItem>
                    <SelectItem value="sitemap">{t("sitemap_based_crawl")}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-1 flex-col gap-2">
                <Label>{t("automatic_updates")}</Label>
                <Select
                  value={updateInterval}
                  onValueChange={(value) => setUpdateInterval(value as UpdateInterval)}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="never">{t("never")}</SelectItem>
                    <SelectItem value="daily">{t("every_day")}</SelectItem>
                    <SelectItem value="every_other_day">{t("every_other_day")}</SelectItem>
                    <SelectItem value="weekly">{t("every_week")}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="flex items-center justify-between gap-4">
              <Label
                htmlFor="website-download-files"
                className={crawlType === "sitemap" ? "opacity-50" : ""}
              >
                {t("download_analyse_files")}
              </Label>
              <Switch
                id="website-download-files"
                disabled={crawlType === "sitemap"}
                checked={downloadFiles}
                onCheckedChange={setDownloadFiles}
              />
            </div>

            {!website && (
              <EmbeddingModelSelect
                models={space.embedding_models}
                value={modelId}
                onChange={setModelId}
              />
            )}

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                {t("cancel")}
              </Button>
              <Button type="submit" disabled={pending || noModels || !url}>
                {website
                  ? pending
                    ? t("saving")
                    : t("save_changes")
                  : pending
                    ? t("creating")
                    : t("create_website")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={existingOnOrg !== null}
        onOpenChange={(next) => {
          if (!next) setExistingOnOrg(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("website_exists_on_org")}</AlertDialogTitle>
            <AlertDialogDescription>
              {existingOnOrg &&
                t("website_exists_on_org_description", { spaceName: existingOnOrg.space_name })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          {existingOnOrg && (
            <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 rounded-md border p-4 text-sm">
              <span className="text-muted-foreground">{t("website_last_crawled")}:</span>
              <span>
                {existingOnOrg.last_crawled_at
                  ? formatDateTime(existingOnOrg.last_crawled_at)
                  : t("website_not_yet_crawled")}
              </span>
              {crawlResult && (
                <>
                  <span className="text-muted-foreground">{t("website_crawl_result")}:</span>
                  <span
                    className={
                      crawlResult.hasFailures
                        ? "text-amber-700 dark:text-amber-500"
                        : "text-green-700 dark:text-green-500"
                    }
                  >
                    {crawlResult.text}
                  </span>
                </>
              )}
              <span className="text-muted-foreground">{t("website_sync_interval")}:</span>
              <span>{intervalLabel(existingOnOrg.update_interval, t)}</span>
            </div>
          )}
          <AlertDialogFooter>
            <Button variant="outline" onClick={() => setExistingOnOrg(null)}>
              {t("go_back")}
            </Button>
            <Button
              disabled={save.isPending}
              onClick={() => {
                setExistingOnOrg(null);
                save.mutate();
              }}
            >
              {save.isPending ? t("creating") : t("create_anyway")}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
