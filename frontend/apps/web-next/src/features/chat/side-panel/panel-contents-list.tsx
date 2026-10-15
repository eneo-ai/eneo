"use client";

import { IconButton } from "@astryxdesign/core/IconButton";
import { Activity, AppWindow, Check, Download } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { FileTypeTile } from "@/features/chat/attachments";
import { signedOriginalUrl } from "@/features/files/signed-original-url";
import { previewKindOf, type PreviewFile } from "@/features/workspace/preview/preview-kind";
import { browserApi } from "@/lib/api/browser";
import { formatBytes } from "@/lib/format";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import type { PanelContents, PanelView } from "./panel-contents";
import type { SidePanelStore } from "./side-panel-store";

/** The activity of an answer, as one more thing the panel can show. */
export type ActivityEntry = {
  detail: string;
  shown: boolean;
  open: () => void;
};

export type PanelContentsListProps = {
  panel: SidePanelStore;
  contents: PanelContents;
  activity?: ActivityEntry | null;
  /** A section to scroll to and focus when the list opens, e.g. from a file bundle. */
  focusSection?: "uploads" | null;
  onFile: (file: PreviewFile) => void;
  onView: (view: PanelView) => void;
};

/** A Markdown document is read in Eneo and listed by its title. */
export function displayFileName(file: { name: string; mimetype: string }): string {
  return previewKindOf(file) === "markdown"
    ? file.name.replace(/\.(md|markdown)$/i, "")
    : file.name;
}

const extensionOf = (name: string) => {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot + 1).toUpperCase() : "";
};
const bytesOf = (file: PreviewFile) => file.original_size ?? file.size;

const ROW_CLASS =
  "focus-visible:outline-ring hover:bg-ax-hover flex h-9 min-w-0 flex-1 items-center gap-2.5 rounded-ax-inner px-2 text-start focus-visible:outline-2 focus-visible:-outline-offset-2";
const CURRENT_CLASS = "bg-ax-accent-muted hover:bg-ax-accent-muted";

function Row({
  tile,
  name,
  detail,
  current
}: {
  tile: React.ReactNode;
  name: string;
  detail: string;
  current: boolean;
}) {
  return (
    <>
      {tile}
      <span className="min-w-0 flex-1 truncate text-[13px] font-medium">{name}</span>
      {detail && (
        <span className="text-ax-text-secondary shrink-0 text-[11.5px] tabular-nums">{detail}</span>
      )}
      {current && <Check aria-hidden="true" className="text-ax-text-accent size-4 shrink-0" />}
    </>
  );
}

function Heading({
  text,
  children,
  ...props
}: { text: string; children?: React.ReactNode } & React.ComponentProps<"h3">) {
  return (
    <h3
      {...props}
      className="text-ax-text-secondary focus-visible:outline-ring rounded-ax-inner px-2 pt-2 pb-1 text-xs font-medium tabular-nums focus-visible:outline-2 focus-visible:outline-offset-2"
    >
      {text}
      {children}
    </h3>
  );
}

/**
 * What a conversation has to show in the panel, as one list: interactive tool
 * views, documents created in the chat, uploaded files and the latest answer's
 * activity. The panel's overview and the switcher in its title both show it.
 */
export function PanelContentsList({
  panel,
  contents,
  activity = null,
  focusSection = null,
  onFile,
  onView
}: PanelContentsListProps) {
  const t = useTranslations();
  const locale = useLocale();
  const uploadsHeading = useRef<HTMLHeadingElement>(null);
  const [downloading, setDownloading] = useState<string | null>(null);

  // Opened on the uploads: the list scrolls there and the heading takes the focus.
  useEffect(() => {
    if (focusSection !== "uploads") return;
    const heading = uploadsHeading.current;
    heading?.scrollIntoView({ block: "start" });
    heading?.focus();
  }, [focusSection]);

  async function download(file: PreviewFile) {
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

  const description = (latest: PreviewFile, versionCount: number) =>
    [
      extensionOf(latest.name),
      bytesOf(latest) > 0 ? formatBytes(bytesOf(latest), locale) : "",
      versionCount > 1 ? t("conversation_document_versions", { count: versionCount }) : ""
    ]
      .filter(Boolean)
      .join(" · ");

  const entry = (file: PreviewFile, versions: PreviewFile[]) => {
    const current = versions.some((version) => panel.isOpen(version));
    const tile = <FileTypeTile mimetype={file.mimetype} size="sm" />;
    return (
      <li key={file.id} className="group flex items-center gap-1">
        {panel.canPreview(file) ? (
          <button
            type="button"
            aria-label={t("file_preview_open", { name: file.name })}
            aria-current={current ? "true" : undefined}
            onClick={() => onFile(file)}
            className={cn(ROW_CLASS, current && CURRENT_CLASS)}
          >
            <Row
              tile={tile}
              name={displayFileName(file)}
              detail={description(file, versions.length)}
              current={current}
            />
          </button>
        ) : (
          <div className="flex h-9 min-w-0 flex-1 items-center gap-2.5 px-2">
            <Row
              tile={tile}
              name={displayFileName(file)}
              detail={description(file, versions.length)}
              current={false}
            />
          </div>
        )}
        <IconButton
          label={t("generated_file_download", { name: file.name })}
          tooltip={t("download")}
          icon={<Download className="size-4" />}
          variant="ghost"
          size="sm"
          isLoading={downloading === file.id}
          onClick={() => void download(file)}
        />
      </li>
    );
  };

  const uploadsBytes = contents.uploads.reduce((sum, file) => sum + bytesOf(file), 0);

  return (
    <div className="flex flex-col p-1">
      {contents.views.length > 0 && (
        <section aria-label={t("conversation_documents_views")}>
          <Heading text={`${t("conversation_documents_views")} · ${contents.views.length}`} />
          <ul className="flex flex-col">
            {contents.views.map((view) => (
              <li key={view.id} className="flex">
                <button
                  type="button"
                  aria-current={view.shown ? "true" : undefined}
                  onClick={() => onView(view)}
                  className={cn(ROW_CLASS, view.shown && CURRENT_CLASS)}
                >
                  {/* A view that says what it is about is listed by that, above its tool. */}
                  <Row
                    tile={
                      <span
                        aria-hidden="true"
                        className="bg-ax-teal-muted text-ax-teal rounded-ax-inner flex size-[22px] shrink-0 items-center justify-center"
                      >
                        <AppWindow className="size-[13px]" />
                      </span>
                    }
                    name={view.subject ?? view.title}
                    detail={view.subject ? view.title : t("mcp_app_view_title")}
                    current={view.shown}
                  />
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
      {contents.documents.length > 0 && (
        <section aria-label={t("conversation_documents_created")}>
          <Heading text={`${t("conversation_documents_created")} · ${contents.documents.length}`} />
          <ul className="flex flex-col">
            {contents.documents.map((document) => entry(document.latest, document.versions))}
          </ul>
        </section>
      )}
      {contents.uploads.length > 0 && (
        <section aria-label={t("conversation_documents_uploads")}>
          <Heading
            ref={uploadsHeading}
            tabIndex={-1}
            text={`${t("conversation_documents_uploads")} · ${contents.uploads.length}${
              uploadsBytes > 0 ? ` · ${formatBytes(uploadsBytes, locale)}` : ""
            }`}
          />
          <ul className="flex flex-col">{contents.uploads.map((file) => entry(file, [file]))}</ul>
        </section>
      )}
      {activity && (
        <section aria-label={t("chat_activity_label")}>
          <Heading text={t("chat_activity_label")} />
          <button
            type="button"
            aria-current={activity.shown ? "true" : undefined}
            onClick={activity.open}
            className={cn(ROW_CLASS, "w-full", activity.shown && CURRENT_CLASS)}
          >
            <Row
              tile={
                <span
                  aria-hidden="true"
                  className="bg-ax-muted text-ax-text-secondary rounded-ax-inner flex size-[22px] shrink-0 items-center justify-center"
                >
                  <Activity className="size-[13px]" />
                </span>
              }
              name={t("side_panel_latest_answer")}
              detail={activity.detail}
              current={activity.shown}
            />
          </button>
        </section>
      )}
    </div>
  );
}
