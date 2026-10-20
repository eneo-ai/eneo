"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { FILE_TOKEN_CLASS, FileTokenBody } from "@/features/chat/message-parts";
import { useSidePanel } from "@/features/chat/side-panel/use-side-panel";
import { signedOriginalUrl } from "@/features/files/signed-original-url";
import { browserApi } from "@/lib/api/browser";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import type { FlowRunFilePublic } from "./types";

/** A run's file as the preview panel wants it; the backend may leave type and size out. */
export function previewFileOf(file: FlowRunFilePublic) {
  return { id: file.id, name: file.name, mimetype: file.mimetype ?? "", size: file.size ?? 0 };
}

/**
 * Files a run took in or put out, as chips. A file the panel can show opens
 * there (over the flow panel, which comes back when it closes); any other
 * file downloads.
 */
export function FlowRunFiles({ files, label }: { files: FlowRunFilePublic[]; label: string }) {
  const t = useTranslations();
  const panel = useSidePanel();
  const [downloading, setDownloading] = useState<string | null>(null);
  if (files.length === 0) return null;

  async function download(file: FlowRunFilePublic) {
    setDownloading(file.id);
    try {
      const url = await signedOriginalUrl(browserApi, file.id);
      Object.assign(document.createElement("a"), { href: url, download: file.name }).click();
    } catch {
      toast.error(t("attachment_error_loading_content"));
    } finally {
      setDownloading(null);
    }
  }

  return (
    <ul aria-label={label} className="m-0 flex list-none flex-wrap gap-1.5 p-0">
      {files.map((file) => {
        const preview = previewFileOf(file);
        const previewable = panel?.canPreview(preview) ?? false;
        const shown = previewable && (panel?.isOpen(preview) ?? false);
        return (
          <li key={file.id} className="max-w-full">
            <button
              type="button"
              aria-label={
                previewable
                  ? t("file_preview_open", { name: file.name })
                  : t("generated_file_download", { name: file.name })
              }
              aria-expanded={previewable ? shown : undefined}
              aria-busy={downloading === file.id || undefined}
              onClick={(event) => {
                if (previewable && panel) panel.toggle(preview, event.currentTarget);
                else if (downloading !== file.id) void download(file);
              }}
              className={cn(FILE_TOKEN_CLASS, shown && "border-ax-accent bg-ax-accent-muted")}
            >
              <FileTokenBody name={file.name} mimetype={preview.mimetype} size={preview.size} />
            </button>
          </li>
        );
      })}
    </ul>
  );
}
