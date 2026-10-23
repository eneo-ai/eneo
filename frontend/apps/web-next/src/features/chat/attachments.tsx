"use client";

import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent } from "@astryxdesign/core/Layout";
import { ProgressBar } from "@astryxdesign/core/ProgressBar";
import { Spinner } from "@astryxdesign/core/Spinner";
import {
  ChevronDown,
  ChevronUp,
  Download,
  File,
  FileSpreadsheet,
  FileText,
  ImageIcon,
  Paperclip,
  X
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { useReturnFocus } from "@/components/ui/dialog-focus";
import { browserApi } from "@/lib/api/browser";
import { signedFileUrl } from "@/features/files/signed-file-url";
import { cn } from "@/lib/utils";
import { fileExtension, formatBytes } from "@/lib/format";
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
  const [result, setResult] = useState<{
    fileId: string;
    url: string | null;
    error: boolean;
  } | null>(null);

  useEffect(() => {
    let active = true;
    signedFileUrl(browserApi, fileId, "inline")
      .then((url) => {
        if (active) setResult({ fileId, url, error: false });
      })
      .catch(() => {
        if (active) setResult({ fileId, url: null, error: true });
      });
    return () => {
      active = false;
    };
  }, [fileId]);

  return result?.fileId === fileId ? result : { fileId, url: null, error: false };
}

/** Native link preserves the backend's slash-sensitive download path. */
function DownloadPreviewLink({ url }: { url: string }) {
  const t = useTranslations();
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      className="bg-primary text-primary-foreground hover:bg-primary/90 focus-visible:outline-ring inline-flex min-h-9 items-center gap-2 rounded-md px-4 py-2 text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:min-h-11"
    >
      <Download aria-hidden="true" className="size-4" />
      {t("download")}
    </a>
  );
}

/** PDF bytes stay in a local blob frame, never an external backend frame. */
function PdfPreview({ url, name }: { url: string; name: string }) {
  const t = useTranslations();
  const [preview, setPreview] = useState<
    { source: string; blobUrl: string } | { source: string; error: true } | null
  >(null);

  useEffect(() => {
    if (url.startsWith("blob:")) return;
    const controller = new AbortController();
    let blobUrl: string | null = null;
    fetch(url, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("Unable to load PDF preview");
        return response.blob();
      })
      .then((blob) => {
        if (controller.signal.aborted) return;
        blobUrl = URL.createObjectURL(blob);
        setPreview({ source: url, blobUrl });
      })
      .catch(() => {
        if (!controller.signal.aborted) setPreview({ source: url, error: true });
      });
    return () => {
      controller.abort();
      if (blobUrl) URL.revokeObjectURL(blobUrl);
    };
  }, [url]);

  if (!url.startsWith("blob:") && (!preview || preview.source !== url)) {
    return <Spinner size="lg" aria-label={t("loading")} />;
  }
  if (preview && "error" in preview && preview.source === url) {
    return (
      <div className="flex flex-col items-center gap-3">
        <p className="text-muted-foreground text-sm">{t("attachment_error_loading_content")}</p>
        <DownloadPreviewLink url={url} />
      </div>
    );
  }
  return (
    <iframe
      src={
        url.startsWith("blob:")
          ? url
          : preview && "blobUrl" in preview
            ? preview.blobUrl
            : undefined
      }
      title={name}
      className="border-ax-border rounded-ax-element h-[70dvh] w-full border"
    />
  );
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
  url,
  error = false
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  name: string;
  mimetype: string;
  url: string | null;
  error?: boolean;
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
              {error ? (
                <p className="text-muted-foreground text-sm">
                  {t("attachment_error_loading_content")}
                </p>
              ) : !url ? (
                <Spinner size="lg" aria-label={t("loading")} />
              ) : isImage ? (
                // eslint-disable-next-line @next/next/no-img-element -- signed/object URL
                <img
                  src={url}
                  alt={name}
                  className="rounded-ax-element max-h-[70dvh] max-w-full object-contain"
                />
              ) : isPdf ? (
                <PdfPreview url={url} name={name} />
              ) : (
                <DownloadPreviewLink url={url} />
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
  const extension = size === "lg" && name ? fileExtension(name) || null : null;
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
 * From this many attachments the composer folds the list into a summary row.
 * Two chips split one row between them; a third would already stack.
 */
export const SUMMARY_FROM = 3;

const SMALL_BUTTON_CLASS =
  "text-ax-text-secondary hover:text-ax-text hover:bg-ax-hover focus-visible:outline-ring rounded-ax-inner inline-flex h-6 shrink-0 items-center gap-1 px-1.5 text-xs font-medium focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:h-11";

/**
 * One attachment waiting in the composer: type tile (a spinner while it
 * uploads), name, type and size, a preview on click and a named remove button.
 */
function AttachmentChip({
  item,
  onPreview,
  onRemove
}: {
  item: Attachment;
  onPreview: () => void;
  onRemove: () => void;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const detail = item.uploading
    ? t("chat_attachment_uploading")
    : [fileExtension(item.name), formatBytes(item.size, locale)].filter(Boolean).join(" · ");
  const body = (
    <>
      <FileTypeTile mimetype={item.mimetype} size="sm" uploading={item.uploading} />
      <span className="min-w-0 flex-1 truncate text-[12.5px] font-semibold">{item.name}</span>
      <span className="text-ax-text-secondary shrink-0 text-[11.5px] tabular-nums">{detail}</span>
    </>
  );
  return (
    <div
      className="border-ax-border bg-ax-surface rounded-ax-element flex h-8 max-w-full min-w-0 items-center gap-1 border ps-1 pe-0.5 pointer-coarse:h-11"
      title={item.name}
    >
      {item.previewUrl ? (
        <button
          type="button"
          onClick={onPreview}
          className="focus-visible:outline-ring rounded-ax-inner flex min-w-0 flex-1 items-center gap-2 text-start focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          <span className="sr-only">{t("preview")}: </span>
          {body}
        </button>
      ) : (
        <span className="flex min-w-0 flex-1 items-center gap-2">{body}</span>
      )}
      <button
        type="button"
        aria-label={t("chat_attachment_remove", { name: item.name })}
        onClick={onRemove}
        className="text-ax-text-secondary hover:bg-ax-hover hover:text-ax-text focus-visible:outline-ring rounded-ax-inner flex size-6 shrink-0 items-center justify-center focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:size-11"
      >
        <X className="size-3.5" aria-hidden="true" />
      </button>
    </div>
  );
}

/**
 * The attachments waiting in the composer (inside its drawer). One or two are
 * chips sharing a row; more fold into one summary row with the count, the
 * total size and the upload progress that unfolds to the chips on request, so
 * a long list never pushes the composer down. The side panel holds the full
 * list once the message is sent.
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
  const locale = useLocale();
  const [preview, setPreview] = useState<PendingPreview | null>(null);
  const [expanded, setExpanded] = useState(false);
  const items = attachments.attachments;

  if (items.length === 0) return null;

  const countLabel =
    items.length === 1
      ? t("attachments_count_one", { count: items.length })
      : t("attachments_count_other", { count: items.length });
  const done = items.filter((item) => !item.uploading).length;
  const bytes = items.reduce((sum, item) => sum + item.size, 0);
  const summarised = items.length >= SUMMARY_FROM;

  const chips = (
    <ul
      aria-label={countLabel}
      className={cn(
        "gap-1.5",
        items.length === 1 ? "flex flex-wrap" : "grid grid-cols-1 sm:grid-cols-2",
        summarised && "max-h-[146px] [scrollbar-width:thin] auto-rows-max overflow-y-auto pr-0.5"
      )}
    >
      {items.map((item) => (
        <li key={item.key} className="max-w-full min-w-0">
          <AttachmentChip
            item={item}
            onPreview={() =>
              item.previewUrl &&
              setPreview({ name: item.name, mimetype: item.mimetype, url: item.previewUrl })
            }
            onRemove={() => attachments.removeAttachment(item.key)}
          />
        </li>
      ))}
    </ul>
  );

  return (
    <div className="flex w-full flex-col gap-1.5">
      {summarised ? (
        <>
          <div className="border-ax-border bg-ax-surface rounded-ax-element flex min-h-10 flex-wrap items-center gap-x-2 gap-y-1 border px-2.5 py-1">
            <Paperclip className="text-ax-text-secondary size-3.5 shrink-0" aria-hidden="true" />
            <span className="shrink-0 text-xs font-medium tabular-nums">{countLabel}</span>
            <span className="text-ax-text-secondary shrink-0 text-xs tabular-nums">
              {`· ${formatBytes(bytes, locale)}`}
            </span>
            {done < items.length && (
              <span className="flex min-w-0 items-center gap-2">
                <span className="w-24 shrink-0">
                  <ProgressBar
                    label={t("uploading")}
                    isLabelHidden
                    value={done}
                    max={items.length}
                  />
                </span>
                <span className="text-ax-text-secondary truncate text-xs tabular-nums">
                  {t("attachments_pending_progress", { done, total: items.length })}
                </span>
              </span>
            )}
            <span className="flex-1" />
            <button
              type="button"
              aria-expanded={expanded}
              onClick={() => setExpanded((current) => !current)}
              className={SMALL_BUTTON_CLASS}
            >
              {expanded ? t("attachments_pending_hide") : t("attachments_pending_show")}
              {expanded ? (
                <ChevronUp className="size-3" aria-hidden="true" />
              ) : (
                <ChevronDown className="size-3" aria-hidden="true" />
              )}
            </button>
            <button
              type="button"
              onClick={() => items.forEach((item) => attachments.removeAttachment(item.key))}
              className={cn(SMALL_BUTTON_CLASS, "-me-1")}
            >
              {t("remove_all_attachments")}
            </button>
          </div>
          {expanded && chips}
        </>
      ) : (
        chips
      )}

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
