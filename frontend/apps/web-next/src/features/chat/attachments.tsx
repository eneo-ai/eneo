"use client";

import {
  Download,
  File,
  FileSpreadsheet,
  FileText,
  ImageIcon,
  Loader2,
  Paperclip,
  X
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { formatBytes } from "@/lib/format";
import type { Attachment } from "./use-attachments";

/** A representative icon for an attachment, chosen from its mime type. */
export function FileKindIcon({ mimetype, className }: { mimetype: string; className?: string }) {
  if (mimetype.startsWith("image/")) return <ImageIcon aria-hidden className={className} />;
  if (mimetype === "application/pdf") return <FileText aria-hidden className={className} />;
  if (mimetype.includes("sheet") || mimetype.includes("csv") || mimetype.includes("excel")) {
    return <FileSpreadsheet aria-hidden className={className} />;
  }
  return <File aria-hidden className={className} />;
}

/** Resolves a short-lived inline signed URL for a backend file on mount. */
export function useSignedUrl(fileId: string) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    unwrap(
      browserApi.POST("/api/v1/files/{id}/signed-url/", {
        params: { path: { id: fileId } },
        body: { expires_in: 3600, content_disposition: "inline" }
      })
    )
      .then((signed) => {
        if (active) setUrl(signed.url);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [fileId]);

  return url;
}

/**
 * Full-screen preview of a single attachment: images render inline, PDFs in an
 * iframe, everything else falls back to a download link. `url` may be null while
 * a signed URL is still resolving.
 */
export function AttachmentPreviewDialog({
  open,
  onOpenChange,
  name,
  mimetype,
  url
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  name: string;
  mimetype: string;
  url: string | null;
}) {
  const t = useTranslations();
  const isImage = mimetype.startsWith("image/");
  const isPdf = mimetype === "application/pdf";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[95vw] gap-0 overflow-hidden p-0 sm:max-w-5xl">
        <DialogHeader className="border-b px-4 py-3">
          <DialogTitle className="truncate pr-6 text-sm font-medium">{name}</DialogTitle>
          <DialogDescription className="sr-only">{t("preview")}</DialogDescription>
        </DialogHeader>
        <div className="flex max-h-[82vh] min-h-40 items-center justify-center overflow-auto p-4">
          {!url ? (
            <Loader2
              aria-label={t("loading")}
              className="text-muted-foreground size-6 animate-spin"
            />
          ) : isImage ? (
            // eslint-disable-next-line @next/next/no-img-element -- signed/object URL
            <img
              src={url}
              alt={name}
              className="max-h-[78vh] max-w-full rounded-md object-contain"
            />
          ) : isPdf ? (
            <iframe src={url} title={name} className="h-[78vh] w-full rounded-md border" />
          ) : (
            <a
              href={url}
              target="_blank"
              rel="noreferrer"
              className="bg-primary text-primary-foreground hover:bg-primary/90 inline-flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors"
            >
              <Download className="size-4" aria-hidden /> {t("download")}
            </a>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

type PendingPreview = { name: string; mimetype: string; url: string };

/**
 * Composer attachment tray: uniform file cards in a capped, scrollable grid
 * (ported from the Svelte ConversationAttachments). Each card opens a preview;
 * a "remove all" affordance appears once there is more than one.
 */
export function ComposerAttachments({
  attachments
}: {
  attachments: {
    attachments: Attachment[];
    removeAttachment: (key: string) => void;
  };
}) {
  const t = useTranslations();
  const [preview, setPreview] = useState<PendingPreview | null>(null);
  const items = attachments.attachments;

  if (items.length === 0) return null;

  return (
    <div className="flex w-full flex-col gap-2 pb-2">
      {items.length > 1 && (
        <div className="flex items-center justify-between px-0.5">
          <div className="text-muted-foreground flex items-center gap-1.5 text-xs">
            <Paperclip className="size-3.5" aria-hidden />
            <span className="tabular-nums">
              {t("attachments_count_other", { count: items.length })}
            </span>
          </div>
          <button
            type="button"
            onClick={() => items.forEach((item) => attachments.removeAttachment(item.key))}
            className="text-muted-foreground hover:text-foreground -mr-1 rounded px-1.5 py-0.5 text-xs transition-colors"
          >
            {t("remove_all_attachments")}
          </button>
        </div>
      )}

      <div
        role="list"
        aria-label={t("attachments_count_other", { count: items.length })}
        className="grid max-h-[200px] auto-rows-max grid-cols-1 gap-2 overflow-y-auto pr-0.5 [scrollbar-width:thin] sm:grid-cols-2"
      >
        {items.map((item) => {
          return (
            <div
              key={item.key}
              role="listitem"
              className="group bg-card hover:bg-accent relative flex h-11 min-w-0 items-center gap-2 rounded-lg border py-1.5 pr-2 pl-1.5 shadow-sm transition-colors"
            >
              <button
                type="button"
                aria-label={item.name}
                disabled={!item.previewUrl}
                onClick={() =>
                  item.previewUrl &&
                  setPreview({ name: item.name, mimetype: item.mimetype, url: item.previewUrl })
                }
                className="flex min-w-0 flex-1 items-center gap-2 text-left"
              >
                <span className="bg-muted text-muted-foreground flex size-8 shrink-0 items-center justify-center rounded-md">
                  {item.uploading ? (
                    <Loader2 className="size-4 animate-spin" aria-hidden />
                  ) : (
                    <FileKindIcon mimetype={item.mimetype} className="size-4" />
                  )}
                </span>
                <span className="flex min-w-0 flex-1 flex-col leading-tight">
                  <span className="truncate text-sm font-medium">{item.name}</span>
                  <span className="text-muted-foreground truncate text-[11px] tabular-nums">
                    {formatBytes(item.size)}
                  </span>
                </span>
              </button>
              <button
                type="button"
                aria-label={t("remove_this_attachment")}
                onClick={() => attachments.removeAttachment(item.key)}
                className="text-muted-foreground hover:bg-destructive hover:text-destructive-foreground size-5 shrink-0 rounded-full opacity-60 transition-all group-hover:opacity-100"
              >
                <X className="size-3" aria-hidden />
              </button>
            </div>
          );
        })}
      </div>

      <AttachmentPreviewDialog
        open={preview !== null}
        onOpenChange={(next) => !next && setPreview(null)}
        name={preview?.name ?? ""}
        mimetype={preview?.mimetype ?? ""}
        url={preview?.url ?? null}
      />
    </div>
  );
}
