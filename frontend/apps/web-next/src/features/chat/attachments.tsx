"use client";

import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent } from "@astryxdesign/core/Layout";
import { Spinner } from "@astryxdesign/core/Spinner";
import { Download, File, FileSpreadsheet, FileText, ImageIcon, Paperclip, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { useReturnFocus } from "@/components/ui/dialog-focus";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { cn } from "@/lib/utils";
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
 * Preview of a single attachment in an Astryx Dialog: images render inline,
 * PDFs in an iframe, everything else falls back to a download link. `url` may
 * be null while a signed URL is still resolving.
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
  const noTrigger = useRef<HTMLElement>(null);
  // Focus goes back to the file that was opened (also after a tap in Safari).
  useReturnFocus(open, noTrigger);
  const isImage = mimetype.startsWith("image/");
  const isPdf = mimetype === "application/pdf";

  return (
    <Dialog isOpen={open} onOpenChange={onOpenChange} width="min(64rem, 95vw)" maxHeight="90dvh">
      <Layout
        header={<DialogHeader title={name} subtitle={t("preview")} onOpenChange={onOpenChange} />}
        content={
          <LayoutContent>
            <div className="flex min-h-40 items-center justify-center">
              {!url ? (
                <Spinner size="lg" aria-label={t("loading")} />
              ) : isImage ? (
                // eslint-disable-next-line @next/next/no-img-element -- signed/object URL
                <img
                  src={url}
                  alt={name}
                  className="rounded-ax-element max-h-[70dvh] max-w-full object-contain"
                />
              ) : isPdf ? (
                <iframe
                  src={url}
                  title={name}
                  className="border-ax-border rounded-ax-element h-[70dvh] w-full border"
                />
              ) : (
                <Button
                  label={t("download")}
                  variant="primary"
                  icon={<Download className="size-4" aria-hidden="true" />}
                  href={url}
                  target="_blank"
                  rel="noreferrer"
                />
              )}
            </div>
          </LayoutContent>
        }
      />
    </Dialog>
  );
}

type PendingPreview = { name: string; mimetype: string; url: string };

type FileKind = "pdf" | "doc" | "sheet" | "image" | "other";

function fileKind(mimetype: string): FileKind {
  if (mimetype.startsWith("image/")) return "image";
  if (mimetype === "application/pdf") return "pdf";
  if (mimetype.includes("sheet") || mimetype.includes("csv") || mimetype.includes("excel")) {
    return "sheet";
  }
  if (mimetype.includes("word") || mimetype.includes("document") || mimetype.startsWith("text/")) {
    return "doc";
  }
  return "other";
}

// Full static class strings so Tailwind keeps them.
const FILE_TONE: Record<FileKind, string> = {
  pdf: "bg-ax-pink-muted text-ax-pink",
  doc: "bg-ax-blue-muted text-ax-blue",
  sheet: "bg-ax-green-muted text-ax-green",
  image: "bg-ax-purple-muted text-ax-purple",
  other: "bg-ax-muted text-ax-text-secondary"
};

function extensionOf(name: string): string | null {
  const match = /\.([a-z0-9]{1,5})$/i.exec(name);
  return match ? match[1]!.toUpperCase() : null;
}

/**
 * Decorative file-type tile: a coloured square with the type icon (small) or
 * the file extension (large). The file name next to it carries the meaning.
 */
export function FileTypeTile({
  mimetype,
  name,
  size = "sm",
  uploading = false
}: {
  mimetype: string;
  name?: string;
  size?: "sm" | "lg";
  uploading?: boolean;
}) {
  const kind = fileKind(mimetype);
  const extension = size === "lg" && name ? extensionOf(name) : null;
  return (
    <span
      aria-hidden="true"
      className={cn(
        "flex shrink-0 items-center justify-center font-bold",
        FILE_TONE[kind],
        size === "lg"
          ? "rounded-ax-inner size-9 text-[10px] tracking-wide"
          : "rounded-ax-inner size-[22px]"
      )}
    >
      {uploading ? (
        // Decorative (the tile is aria-hidden); the row's text says "Laddar upp…".
        <Spinner size={size === "lg" ? "md" : "sm"} shade="inherit" />
      ) : extension ? (
        extension
      ) : (
        <FileKindIcon mimetype={mimetype} className={size === "lg" ? "size-4" : "size-[13px]"} />
      )}
    </span>
  );
}

/**
 * Composer attachment cards (inside the composer drawer): type tile, name,
 * size and upload status, a preview on click and a named remove button. A
 * "remove all" action appears once there is more than one.
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
    <div className="flex w-full flex-col gap-2">
      {items.length > 1 && (
        <div className="flex items-center justify-between gap-2">
          <span className="text-ax-text-secondary flex items-center gap-1.5 text-xs tabular-nums">
            <Paperclip className="size-3.5" aria-hidden="true" />
            {t("attachments_count_other", { count: items.length })}
          </span>
          <button
            type="button"
            onClick={() => items.forEach((item) => attachments.removeAttachment(item.key))}
            className="text-ax-text-secondary hover:text-ax-text focus-visible:outline-ring rounded-ax-inner min-h-6 px-1.5 text-xs font-medium focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            {t("remove_all_attachments")}
          </button>
        </div>
      )}

      <ul
        aria-label={t("attachments")}
        className="flex max-h-[200px] [scrollbar-width:thin] flex-wrap gap-2 overflow-y-auto"
      >
        {items.map((item) => (
          <li
            key={item.key}
            className="bg-ax-muted rounded-ax-container flex min-h-[50px] max-w-full min-w-0 items-center gap-1 ps-1.5 pe-1"
          >
            <button
              type="button"
              disabled={!item.previewUrl}
              onClick={() =>
                item.previewUrl &&
                setPreview({ name: item.name, mimetype: item.mimetype, url: item.previewUrl })
              }
              className="focus-visible:outline-ring rounded-ax-element flex min-w-0 items-center gap-2.5 py-1.5 pe-1 text-start focus-visible:outline-2 focus-visible:outline-offset-2"
            >
              <FileTypeTile
                mimetype={item.mimetype}
                name={item.name}
                size="lg"
                uploading={item.uploading}
              />
              <span className="flex min-w-0 flex-col leading-tight">
                <span className="max-w-[16rem] truncate text-[13px] font-semibold">
                  <span className="sr-only">{t("preview")}: </span>
                  {item.name}
                </span>
                <span className="text-ax-text-secondary text-xs tabular-nums">
                  {formatBytes(item.size)} ·{" "}
                  {item.uploading ? t("chat_attachment_uploading") : t("chat_attachment_ready")}
                </span>
              </span>
            </button>
            <button
              type="button"
              aria-label={t("chat_attachment_remove", { name: item.name })}
              onClick={() => attachments.removeAttachment(item.key)}
              className="text-ax-text-secondary hover:bg-ax-hover hover:text-ax-text focus-visible:outline-ring rounded-ax-element flex size-7 shrink-0 items-center justify-center focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:size-11"
            >
              <X className="size-3.5" aria-hidden="true" />
            </button>
          </li>
        ))}
      </ul>

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
