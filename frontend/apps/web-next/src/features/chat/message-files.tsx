"use client";

import { ProgressBar } from "@astryxdesign/core/ProgressBar";
import { Spinner } from "@astryxdesign/core/Spinner";
import { ArrowUpRight, Check, ChevronDown, ChevronUp, Files } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import type { Schema } from "@/lib/api/models";
import { fileExtension, formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";
import { AttachmentPreviewDialog, FileTypeTile, useSignedUrl } from "./attachments";
import { FILE_CHIP_CLASS, FILE_TOKEN_CLASS, FileTokenBody, InlineImage } from "./message-parts";
import { useSidePanel } from "./side-panel/use-side-panel";

type MessageFile = Schema<"FilePublic">;

/** From this many documents a message shows one bundle instead of chips. */
export const BUNDLE_FROM = 4;

/** An attachment of a sent question that is still on its way to the server. */
export type PendingUpload = {
  key: string;
  name: string;
  size: number;
  mimetype: string;
  uploading: boolean;
};

/** The downloaded file's size; `size` counts the extracted text of a document. */
const bytesOf = (file: { size: number; original_size?: number | null }) =>
  file.original_size ?? file.size;

const isImage = (file: { mimetype: string }) => file.mimetype.startsWith("image/");

/** The first names, how many of each type, and the total size on one line. */
export function summarizeFiles(
  files: readonly { name: string; size: number; original_size?: number | null }[],
  unknownType: string,
  locale: string
): string {
  const names =
    files
      .slice(0, 3)
      .map((file) => file.name)
      .join(", ") + (files.length > 3 ? "…" : "");
  const counts = new Map<string, number>();
  for (const file of files) {
    const type = fileExtension(file.name) || unknownType;
    counts.set(type, (counts.get(type) ?? 0) + 1);
  }
  const types = [...counts]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([type, count]) => `${type} ${count}`);
  const bytes = files.reduce((sum, file) => sum + bytesOf(file), 0);
  return [names, ...types, bytes > 0 ? formatBytes(bytes, locale) : ""].filter(Boolean).join(" · ");
}

const BUNDLE_CLASS =
  "border-ax-border bg-ax-surface rounded-ax-element flex min-h-12 w-full max-w-[42rem] items-center gap-3 border px-3 py-1.5 text-start";
const BUNDLE_BUTTON_CLASS =
  "hover:bg-ax-hover focus-visible:outline-ring transition-colors focus-visible:outline-2 focus-visible:outline-offset-2";
const BUNDLE_SHOWN_CLASS = "border-ax-accent";

/** Opens a message attachment in the shared preview dialog (signs the URL on open). */
function MessageFilePreview({ file, onClose }: { file: MessageFile; onClose: () => void }) {
  const { url, error } = useSignedUrl(file.id);
  return (
    <AttachmentPreviewDialog
      open
      onOpenChange={(next) => !next && onClose()}
      name={file.name}
      mimetype={file.mimetype}
      url={url}
      error={error}
    />
  );
}

/**
 * The files a question was sent with. Images keep their thumbnails. Up to
 * three documents are chips that open the file in the side panel (or the
 * preview dialog where the panel cannot show it); more are one bundle that
 * opens the panel's full list of uploads, so a long upload list never
 * stretches the chat. Without a panel (a transcript) the bundle unfolds in place.
 */
export function MessageFiles({ files }: { files: MessageFile[] }) {
  const t = useTranslations();
  const locale = useLocale();
  const panel = useSidePanel();
  const [preview, setPreview] = useState<MessageFile | null>(null);
  const [expanded, setExpanded] = useState(false);
  // The bundle button as rendered, so the render can tell whether it is what
  // opened the panel's overview.
  const [bundle, setBundle] = useState<HTMLButtonElement | null>(null);
  if (files.length === 0) return null;

  const images = files.filter(isImage);
  const documents = files.filter((file) => !isImage(file));
  const bundled = documents.length >= BUNDLE_FROM;
  // The bundle is the opener of the panel's overview while that is on show.
  const bundleShown = panel !== null && bundle !== null && panel.overview?.opener === bundle;

  const openDocument = (file: MessageFile, trigger: HTMLElement) => {
    if (panel?.canPreview(file)) {
      if (panel.isOpen(file)) panel.close();
      else panel.open(file, trigger);
    } else {
      setPreview(file);
    }
  };

  const toggleBundle = (trigger: HTMLButtonElement) => {
    if (!panel) setExpanded((current) => !current);
    else if (bundleShown) panel.closeOverview();
    else panel.showOverview("uploads", trigger);
  };

  const chips = (
    <ul aria-label={t("attachments")} className="flex max-w-[42rem] flex-wrap justify-end gap-1.5">
      {documents.map((file) => {
        const previewable = panel?.canPreview(file) ?? false;
        const shown = previewable && (panel?.isOpen(file) ?? false);
        return (
          <li key={file.id} className="max-w-full">
            <button
              type="button"
              aria-label={t("file_preview_open", { name: file.name })}
              aria-expanded={previewable ? shown : undefined}
              onClick={(event) => openDocument(file, event.currentTarget)}
              className={cn(FILE_TOKEN_CLASS, shown && "border-ax-accent bg-ax-accent-muted")}
            >
              <FileTokenBody name={file.name} mimetype={file.mimetype} size={bytesOf(file)} />
            </button>
          </li>
        );
      })}
    </ul>
  );

  return (
    <div className="flex w-full max-w-full flex-col items-end gap-1.5">
      {images.length > 0 && (
        <ul className="flex flex-wrap justify-end gap-1.5" aria-label={t("attachments")}>
          {images.map((file) => (
            <li key={file.id}>
              <button
                type="button"
                aria-label={t("chat_preview_file", { name: file.name })}
                onClick={() => setPreview(file)}
                className="focus-visible:outline-ring rounded-ax-container block focus-visible:outline-2 focus-visible:outline-offset-2"
              >
                <InlineImage file={file} />
              </button>
            </li>
          ))}
        </ul>
      )}
      {bundled ? (
        <>
          <button
            ref={setBundle}
            type="button"
            aria-expanded={panel ? bundleShown : expanded}
            aria-label={t("attachments_bundle_open_label", { count: documents.length })}
            onClick={(event) => toggleBundle(event.currentTarget)}
            className={cn(BUNDLE_CLASS, BUNDLE_BUTTON_CLASS, bundleShown && BUNDLE_SHOWN_CLASS)}
          >
            <span
              aria-hidden="true"
              className="bg-ax-accent-muted text-ax-text-accent rounded-ax-inner flex size-9 shrink-0 items-center justify-center"
            >
              <Files className="size-4" />
            </span>
            <span className="flex min-w-0 flex-1 flex-col leading-tight">
              <span className="truncate text-[13px] font-semibold">
                {t("attachments_bundle_title", { count: documents.length })}
              </span>
              <span className="text-ax-text-secondary truncate text-[11.5px] tabular-nums">
                {summarizeFiles(documents, t("unknown"), locale)}
              </span>
            </span>
            <span className="text-ax-text-secondary flex shrink-0 items-center gap-1 text-xs">
              {!panel ? (
                <>
                  {expanded ? t("attachments_show_less") : t("attachments_pending_show")}
                  {expanded ? (
                    <ChevronUp aria-hidden="true" className="size-3.5" />
                  ) : (
                    <ChevronDown aria-hidden="true" className="size-3.5" />
                  )}
                </>
              ) : bundleShown ? (
                <>
                  {t("attachments_bundle_shown")}
                  <Check aria-hidden="true" className="size-3.5" />
                </>
              ) : (
                <>
                  {t("attachments_bundle_open")}
                  <ArrowUpRight aria-hidden="true" className="size-3.5" />
                </>
              )}
            </span>
          </button>
          {!panel && expanded && chips}
        </>
      ) : (
        documents.length > 0 && chips
      )}
      {preview && <MessageFilePreview file={preview} onClose={() => setPreview(null)} />}
    </div>
  );
}

/**
 * The attachments of a question sent before they had all finished uploading:
 * the message waits in the conversation and mirrors their progress here until
 * the request is issued. Four or more are one bundle with a progress bar;
 * fewer are chips that each say whether they are done.
 */
export function PendingMessageFiles({ uploads }: { uploads: readonly PendingUpload[] }) {
  const t = useTranslations();
  const locale = useLocale();
  if (uploads.length === 0) return null;
  const done = uploads.filter((upload) => !upload.uploading).length;

  if (uploads.length >= BUNDLE_FROM) {
    return (
      <div className={BUNDLE_CLASS}>
        <span
          aria-hidden="true"
          className="bg-ax-accent-muted text-ax-text-accent rounded-ax-inner flex size-9 shrink-0 items-center justify-center"
        >
          <Spinner size="md" shade="inherit" />
        </span>
        <span className="flex min-w-0 flex-1 flex-col gap-1 leading-tight">
          <span className="truncate text-[13px] font-semibold">
            {t("attachments_bundle_title", { count: uploads.length })}
          </span>
          <span className="text-ax-text-secondary flex items-center gap-2 text-[11.5px] tabular-nums">
            <span className="w-24 shrink-0">
              <ProgressBar label={t("uploading")} isLabelHidden value={done} max={uploads.length} />
            </span>
            {t("attachments_pending_progress", { done, total: uploads.length })}
          </span>
        </span>
      </div>
    );
  }

  return (
    <ul aria-label={t("attachments")} className="flex max-w-[42rem] flex-wrap justify-end gap-1.5">
      {uploads.map((upload) => (
        <li key={upload.key} className="max-w-full">
          <span className={FILE_CHIP_CLASS} title={upload.name}>
            <FileTypeTile mimetype={upload.mimetype} size="sm" uploading={upload.uploading} />
            <span className="min-w-0 truncate font-semibold">{upload.name}</span>
            <span className="text-ax-text-secondary shrink-0">
              {upload.uploading
                ? t("chat_attachment_uploading")
                : [fileExtension(upload.name), formatBytes(upload.size, locale)]
                    .filter(Boolean)
                    .join(" · ")}
            </span>
          </span>
        </li>
      ))}
    </ul>
  );
}
