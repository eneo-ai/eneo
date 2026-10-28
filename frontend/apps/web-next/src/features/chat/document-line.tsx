"use client";

import { IconButton } from "@astryxdesign/core/IconButton";
import { Download, FileText } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { saveUrl, toastDownloadError } from "@/features/files/signed-file-url";
import { signedOriginalUrl } from "@/features/files/signed-original-url";
import { previewKindOf } from "@/features/workspace/preview/preview-kind";
import { browserApi } from "@/lib/api/browser";
import { cn } from "@/lib/utils";
import type { DocumentDraft } from "./side-panel/document-draft";
import { displayFileName } from "./side-panel/panel-contents-list";
import type { GeneratedDocument } from "./side-panel/document-versions";
import { useSidePanel } from "./side-panel/use-side-panel";

export type DocumentLineKind = "created" | "updated" | "exported";

const LABEL_KEY: Record<DocumentLineKind, string> = {
  created: "tool_document_created",
  updated: "tool_document_updated",
  exported: "tool_result_exported"
};

/**
 * A document a tool made in this answer, as one line under the answer:
 * "Skapade Projektplan". The line is the document's place in the chat: its
 * name opens it in the side panel, and a file that is downloaded as it was
 * made (Word, a spreadsheet) has its download beside it. A document is never
 * a file card; images stay inline.
 */
export function DocumentLine({ file, kind }: { file: GeneratedDocument; kind: DocumentLineKind }) {
  const t = useTranslations();
  const panel = useSidePanel();
  const [downloading, setDownloading] = useState(false);
  const previewable = panel !== null && previewKindOf(file) !== null;
  const previewing = panel?.isOpen(file) ?? false;
  const name = displayFileName(file);
  // A Markdown document is read in Eneo; any other file offers the download it was made for.
  const downloads = previewKindOf(file) !== "markdown";

  async function download() {
    setDownloading(true);
    try {
      saveUrl(await signedOriginalUrl(browserApi, file.id), file.name);
    } catch (error) {
      toastDownloadError(error, t);
    } finally {
      setDownloading(false);
    }
  }

  // The words around the name, split so the name can be set apart.
  const [before, after] = t(LABEL_KEY[kind], { name: "\u0000" }).split("\u0000");
  const line = (
    <>
      <span
        aria-hidden="true"
        className={cn(
          "rounded-ax-inner flex size-[22px] shrink-0 items-center justify-center",
          previewing ? "bg-ax-accent text-ax-on-accent" : "bg-ax-accent-muted text-ax-text-accent"
        )}
      >
        <FileText className="size-[13px]" />
      </span>
      <span className="truncate">
        {before}
        <span className={cn("font-semibold", previewing ? "text-ax-text-accent" : "text-ax-text")}>
          {name}
        </span>
        {after}
      </span>
    </>
  );

  return (
    <div className="flex max-w-full items-center gap-2 text-sm">
      {previewable ? (
        <button
          type="button"
          aria-label={t("file_preview_open", { name: file.name })}
          aria-expanded={previewing}
          onClick={(event) => panel.toggle(file, event.currentTarget)}
          className="text-ax-text-secondary hover:text-ax-text focus-visible:outline-ring rounded-ax-inner flex min-w-0 items-center gap-2 text-start focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:min-h-11"
        >
          {line}
        </button>
      ) : (
        <span className="text-ax-text-secondary flex min-w-0 items-center gap-2">{line}</span>
      )}
      {(downloads || !previewable) && (
        <IconButton
          label={t("generated_file_download", { name: file.name })}
          tooltip={t("download")}
          icon={<Download className="size-4" />}
          variant="ghost"
          size="sm"
          isLoading={downloading}
          onClick={() => void download()}
        />
      )}
    </div>
  );
}

/**
 * The document the answer is writing now, as one line under it: "Skriver
 * Projektplan". It opens the draft in the side panel, which is the way back
 * to it after the reader closed the panel on it, and the way in on a narrow
 * screen, where the panel does not open by itself.
 */
export function DraftLine({ draft }: { draft: DocumentDraft }) {
  const t = useTranslations();
  const panel = useSidePanel();
  if (!panel) return null;
  const name = draft.title || t("file_preview_untitled_document");
  const previewing = panel.draft?.callId === draft.callId && panel.viewCallId === null;
  const [before, after] = t("tool_document_writing", { name: "\u0000" }).split("\u0000");
  return (
    <div className="flex max-w-full items-center gap-2 text-sm">
      <button
        type="button"
        aria-label={t("tool_step_show_draft", { name })}
        aria-pressed={previewing}
        onClick={() => panel.showDraft(draft)}
        className="text-ax-text-secondary hover:text-ax-text focus-visible:outline-ring rounded-ax-inner flex min-w-0 items-center gap-2 text-start focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:min-h-11"
      >
        <span
          aria-hidden="true"
          className={cn(
            "rounded-ax-inner flex size-[22px] shrink-0 items-center justify-center",
            previewing ? "bg-ax-accent text-ax-on-accent" : "bg-ax-accent-muted text-ax-text-accent"
          )}
        >
          <FileText className="size-[13px]" />
        </span>
        <span className="truncate">
          {before}
          <span
            className={cn("font-semibold", previewing ? "text-ax-text-accent" : "text-ax-text")}
          >
            {name}
          </span>
          {after}
        </span>
      </button>
    </div>
  );
}
