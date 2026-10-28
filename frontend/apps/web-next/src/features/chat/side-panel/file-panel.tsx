"use client";

import { Button } from "@astryxdesign/core/Button";
import { DropdownMenu, DropdownMenuItem } from "@astryxdesign/core/DropdownMenu";
import { IconButton } from "@astryxdesign/core/IconButton";
import { ToggleButton } from "@astryxdesign/core/ToggleButton";
import { useQuery } from "@tanstack/react-query";
import { Check, Diff, Download, FileText, History, RotateCcw } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { ClientTime } from "@/components/composites/client-time";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { FileKindIcon } from "@/features/chat/attachments";
import { saveUrl, toastDownloadError } from "@/features/files/signed-file-url";
import { signedOriginalUrl } from "@/features/files/signed-original-url";
import {
  FilePreviewContent,
  type FilePreviewContentHandle
} from "@/features/workspace/preview/file-preview-content";
import { previewKindOf, type PreviewFile } from "@/features/workspace/preview/preview-kind";
import { browserApi } from "@/lib/api/browser";
import { formatBytes } from "@/lib/format";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import type { DocumentExport } from "./document-export";
import type { DocumentSaver } from "./document-saver";
import { DraftPreview } from "./draft-preview";
import { ExportMenu } from "./export-menu";
import { displayFileName } from "./panel-contents-list";
import { PanelFrame, type PanelMaximise, type PanelSwitcher } from "./panel-frame";
import type { SidePanelStore } from "./side-panel-store";

const extensionOf = (name: string) => {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot + 1).toUpperCase() : "";
};

/**
 * A file in the side panel: the document being written, a loaded file with
 * its versions and export, or the reason it cannot be shown. The content
 * holds per-file state (the active sheet, a rendered frame, the selection),
 * so a replacement is prepared beside it and swapped in once ready.
 *
 * The header holds navigation and identity, so the title keeps its width
 * whatever the document can do. A document row beneath it holds what applies
 * to the document: its versions and export, or, while there are unsaved
 * edits, the save bar in their place.
 */
export function FilePanel({
  panel,
  versionsOf,
  exportOf,
  saverOf,
  switcher,
  maximise,
  narrow
}: {
  panel: SidePanelStore;
  /** Every version of the document a file belongs to, oldest first. */
  versionsOf: (file: PreviewFile) => PreviewFile[];
  /** How a file is exported, for a document that can be; null for any other file. */
  exportOf: (file: PreviewFile) => DocumentExport | null;
  /** How a reader's edit of a file is saved, for a document that can be edited; null for any other file. */
  saverOf: (file: PreviewFile) => DocumentSaver | null;
  switcher: PanelSwitcher | null;
  maximise: PanelMaximise | null;
  /** Shown as a sheet over the conversation, where there is less room. */
  narrow: boolean;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const [downloading, setDownloading] = useState(false);
  // Shared through the panel, so a save in flight keeps its document
  // read-only across a remount of the panel.
  const saving = panel.saving;
  // The content components by file, for the document text the reader has edited.
  const [contents] = useState(() => new Map<string, FilePreviewContentHandle>());

  // Keep the existing renderer mounted while its replacement is prepared.
  const keepingFile = !!panel.file && !!panel.content && panel.status === "ready";
  const draft = keepingFile ? null : panel.draft;
  const updating = keepingFile && (!!panel.draft || !!panel.replacementFile);
  const nextTitle =
    panel.replacementFile?.name || panel.draft?.title || t("file_preview_untitled_document");
  const file = draft ? null : panel.file;

  const bytes = file ? (file.original_size ?? file.size) : 0;
  const title = draft
    ? draft.title || t("file_preview_untitled_document")
    : file
      ? displayFileName(file)
      : "";

  const versions = file ? versionsOf(file) : [];
  const position = versions.findIndex((version) => version.id === file?.id);
  const earlier = position > 0 ? versions[position - 1] : null;
  const later = position >= 0 && position < versions.length - 1 ? versions[position + 1] : null;
  const latest = later ? versions[versions.length - 1] : null;
  // The type and size under the title; a draft and an older version say
  // something else there.
  const detail = (() => {
    if (draft || latest || !file) return undefined;
    const size = `${extensionOf(file.name)}${bytes > 0 ? ` · ${formatBytes(bytes, locale)}` : ""}`;
    return file.revises_file_id ? `${size} · ${t("file_preview_edited_by_you")}` : size;
  })();

  const exporting = file ? exportOf(file) : null;
  const content = panel.content;
  // The latest version of a Markdown document is edited in place. Edits stay
  // in the editor; one save makes one new version. While it is saved the
  // document is read-only: the version saved is the text as it stood when the
  // reader asked, and a keystroke meanwhile would be lost with the editor.
  const saver = file ? saverOf(file) : null;
  // Only the whole document can be edited: a preview cut short would be saved
  // as the whole document, and the part beyond the cut lost.
  const whole = content?.kind === "markdown" && !content.truncated;
  const editable = !!saver && !!file && whole && !draft && !later && !saving;
  // What this version changed against the one before it, when asked for.
  const comparable = !!earlier && content?.kind === "markdown" && !draft;
  const comparing = comparable && panel.showChanges;
  const previous = useQuery({
    queryKey: ["document-text", earlier?.id],
    queryFn: () => panel.loadText(earlier!),
    enabled: comparing && !!earlier,
    // Files never change; a version's text is read once.
    staleTime: Infinity
  });
  const previousMarkdown = comparing ? (previous.data ?? null) : null;

  /** Saves `markdown` as the document's next version; whether it was saved. */
  async function saveAs(target: DocumentSaver, markdown: string) {
    // The save belongs to the editing session it started in: a response that
    // comes after the panel closed or another file opened applies to nothing.
    const request = panel.beginSave();
    try {
      const version = await target.save(markdown);
      request.apply(version, markdown);
      return true;
    } catch {
      toast.error(t("file_preview_save_failed"));
      return false;
    } finally {
      request.finish();
    }
  }

  async function saveEdits() {
    const current = file;
    if (!current || !saver || !panel.dirty || saving) return;
    const markdown = contents.get(current.id)?.getMarkdown();
    if (markdown !== null && markdown !== undefined) await saveAs(saver, markdown);
  }

  // An older version is read, not edited; its text can be brought forward as
  // the newest version instead, as the reader's edit of the latest one.
  const restorer = latest ? saverOf(latest) : null;
  const restorable = !!restorer && whole && !draft;
  async function restoreVersion() {
    if (!restorer || !restorable || content?.kind !== "markdown" || saving) return;
    // The restored text is the text on show, so the panel looks the same
    // afterwards: the confirmation says what happened.
    const number = position + 1;
    if (await saveAs(restorer, content.text)) {
      toast.success(t("file_preview_version_restored", { number }));
    }
  }

  /** The reader drops their edits: on the Cancel button, or agreeing to in the dialog. */
  function discardEdits() {
    if (file) contents.get(file.id)?.resetEditor();
    if (panel.pendingDiscard) panel.pendingDiscard.proceed();
    else panel.dropEdits();
  }
  const namesImages =
    content?.kind === "markdown" && /!\[[^\]\n]*\]\(eneo-file:[0-9a-f]{32}/.test(content.text);

  async function saveOriginal() {
    if (!file) return;
    setDownloading(true);
    try {
      saveUrl(await signedOriginalUrl(browserApi, file.id), file.name);
    } catch (error) {
      toastDownloadError(error, t);
    } finally {
      setDownloading(false);
    }
  }

  const views =
    file && content && panel.status === "ready"
      ? [
          { file, content, pending: false },
          ...(panel.replacementFile && panel.replacementContent
            ? [{ file: panel.replacementFile, content: panel.replacementContent, pending: true }]
            : [])
        ]
      : [];
  // What to mark in the file: a quote the user asked to see in place, else the
  // quote waiting in the composer, so it stays visible while the question is written.
  const highlight = panel.highlight ?? (panel.quote?.fileId === file?.id ? panel.quote : null);

  // Versions newest first, as the menu lists them: every version with who
  // made it and when, the current one marked.
  const versionRows = versions.map((version, index) => ({ version, number: index + 1 })).reverse();
  const versionMenu = (
    <DropdownMenu
      placement="below"
      alignment="start"
      menuWidth={288}
      hasChevron
      button={{
        label: `${position + 1} / ${versions.length}`,
        tooltip: t("file_preview_versions"),
        variant: "ghost",
        size: "sm",
        icon: <History className="size-4" />
      }}
    >
      {[
        ...versionRows.map((row) => (
          <DropdownMenuItem
            key={row.version.id}
            icon={
              row.version.id === file?.id ? (
                <Check className="size-4" />
              ) : (
                <span className="size-4" aria-hidden="true" />
              )
            }
            label={t("file_preview_version_number", { number: row.number })}
            description={
              <>
                {row.version.revises_file_id
                  ? t("file_preview_edited_by_you")
                  : t("file_preview_version_by_assistant")}
                {row.version.created_at && (
                  <>
                    {" · "}
                    <ClientTime value={row.version.created_at} format="date_time" />
                  </>
                )}
              </>
            }
            onClick={() => panel.open(row.version)}
          />
        ))
      ]}
    </DropdownMenu>
  );

  // The document row shows for a loaded file: its versions, its export, or
  // the save bar while edits are unsaved. A draft has none of these yet.
  const toolbar = !file ? undefined : panel.dirty ? (
    <div
      role="status"
      className="border-ax-border bg-ax-muted flex shrink-0 items-center justify-between gap-2 border-b py-1.5 ps-4 pe-3"
    >
      <span className="text-ax-text-secondary flex min-w-0 items-center gap-2 text-sm">
        <span aria-hidden="true" className="bg-ax-warning size-2 shrink-0 rounded-full" />
        <span className="truncate">{t("file_preview_unsaved_changes")}</span>
      </span>
      <span className="flex shrink-0 items-center gap-1">
        <Button
          label={t("cancel")}
          variant="ghost"
          size="sm"
          isDisabled={saving}
          onClick={discardEdits}
        />
        <Button
          label={saving ? t("file_preview_saving") : t("save")}
          variant="primary"
          size="sm"
          isLoading={saving}
          isInterruptible
          onClick={() => void saveEdits()}
        />
      </span>
    </div>
  ) : (
    <div className="border-ax-border flex shrink-0 items-center justify-between gap-2 border-b py-1.5 ps-3 pe-3">
      {/* What applies to the version on show stands beside its menu: the
          change marks for one with a version before it, and bringing an
          older one forward as the newest. */}
      <span className="flex min-w-0 items-center gap-1">
        {versions.length > 1 && versionMenu}
        {comparable && (
          <ToggleButton
            label={t("file_preview_show_changes")}
            tooltip={t("file_preview_show_changes")}
            icon={<Diff className="size-4" />}
            isIconOnly
            size="sm"
            isPressed={panel.showChanges}
            onPressedChange={(on) => panel.setShowChanges(on)}
          />
        )}
        {restorable && (
          <Button
            label={t("file_preview_restore")}
            tooltip={t("file_preview_restore_version")}
            variant="secondary"
            size="sm"
            icon={<RotateCcw className="size-4" />}
            isLoading={saving}
            isInterruptible
            onClick={() => void restoreVersion()}
          />
        )}
      </span>
      <span className="flex shrink-0 items-center gap-1">
        {exporting ? (
          <ExportMenu
            fileId={file.id}
            title={title}
            namesImages={namesImages}
            exporting={exporting}
            onSaveOriginal={() => void saveOriginal()}
            compact={narrow}
          />
        ) : (
          <IconButton
            label={t("generated_file_download", { name: file.name })}
            tooltip={t("download")}
            icon={<Download className="size-4" />}
            variant="ghost"
            size="sm"
            isLoading={downloading}
            onClick={() => void saveOriginal()}
          />
        )}
      </span>
    </div>
  );

  return (
    <PanelFrame
      icon={
        file ? (
          <FileKindIcon mimetype={file.mimetype} className="size-4" />
        ) : (
          <FileText className="size-4" />
        )
      }
      title={title}
      detail={detail}
      status={
        draft ? (
          <p className="text-ax-text-accent flex items-center gap-1.5 text-xs">
            <span aria-hidden="true" className="bg-ax-accent size-1.5 shrink-0 rounded-full" />
            {t("file_preview_writing")}
          </p>
        ) : latest ? (
          <p className="text-ax-text-secondary flex min-w-0 items-center gap-1.5 text-xs">
            <span className="truncate">
              {file?.revises_file_id
                ? t("file_preview_older_version_edited_by_you")
                : t("file_preview_older_version")}
            </span>
            <button
              type="button"
              className="text-ax-text-accent focus-visible:outline-ring rounded-ax-inner shrink-0 font-medium underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2"
              onClick={() => latest && panel.open(latest)}
            >
              {t("file_preview_show_latest")}
            </button>
          </p>
        ) : undefined
      }
      toolbar={toolbar}
      switcher={switcher}
      maximise={maximise}
      onClose={() => panel.close()}
    >
      {updating && (
        <div className="border-ax-border shrink-0 border-b px-4 py-2 text-sm">
          {panel.replacementError ? (
            <>
              <p>{t("file_preview_update_failed")}</p>
              <Button
                label={t("retry")}
                variant="secondary"
                size="sm"
                className="mt-2"
                onClick={() => panel.retry()}
              />
            </>
          ) : panel.dirty && panel.replacementContent ? (
            // The newer version waits until the reader is done with their edits.
            <>
              <p className="text-ax-text-secondary text-xs">
                {t("file_preview_newer_version_while_editing")}
              </p>
              <Button
                label={t("file_preview_show_latest")}
                variant="secondary"
                size="sm"
                className="mt-2"
                onClick={discardEdits}
              />
            </>
          ) : (
            <>
              <p className="text-ax-text-accent font-medium">
                {t("file_preview_updating", { name: nextTitle })}
              </p>
              <p className="text-ax-text-secondary text-xs">{t("file_preview_keep_current")}</p>
            </>
          )}
        </div>
      )}
      <div className="relative flex min-h-0 flex-1 flex-col">
        {draft ? (
          <DraftPreview draft={draft} />
        ) : !file ? null : panel.status === "loading" ? (
          <p className="text-ax-text-secondary p-6 text-sm">{t("file_preview_loading")}</p>
        ) : panel.status === "too_large" ? (
          <p className="text-ax-text-secondary p-6 text-sm">{t("file_preview_too_large")}</p>
        ) : panel.status === "failed" || !content ? (
          <div className="flex flex-col items-start gap-3 p-6">
            <p className="text-ax-text-secondary text-sm">{t("file_preview_failed")}</p>
            <Button
              label={t("retry")}
              variant="secondary"
              size="sm"
              onClick={() => panel.retry()}
            />
          </div>
        ) : (
          views.map((view) => (
            <div
              key={view.file.id}
              className={cn("absolute inset-0 flex min-h-0 flex-col", view.pending && "invisible")}
              inert={view.pending || undefined}
              aria-hidden={view.pending ? "true" : undefined}
            >
              <FilePreviewContent
                ref={(handle) => {
                  if (handle) contents.set(view.file.id, handle);
                  return () => {
                    contents.delete(view.file.id);
                  };
                }}
                content={view.content}
                title={view.file.name}
                highlight={view.pending ? null : highlight}
                editable={!view.pending && editable}
                edits={view.pending ? null : panel.editsOf(view.file)}
                previousMarkdown={view.pending ? null : previousMarkdown}
                onReady={() => panel.finishReplacement(view.file.id)}
                onError={() => panel.failReplacement(view.file.id)}
                onQuote={(text, locator) => panel.quoteSelection(text, locator)}
                onChange={(text) => panel.setEdits(view.file.id, text)}
                onSave={() => void saveEdits()}
              />
            </div>
          ))
        )}
      </div>
      <ConfirmDialogControlled
        open={panel.pendingDiscard !== null}
        onOpenChange={(open) => {
          if (!open) panel.keepEditing();
        }}
        title={t("file_preview_discard_edits_title")}
        description={t("file_preview_discard_edits_description")}
        confirmLabel={t("file_preview_discard_edits")}
        onConfirm={discardEdits}
      />
    </PanelFrame>
  );
}

/** Whether a file can be exported as Word or PDF: a Markdown document the assistant made here. */
export function isExportableDocument(file: PreviewFile): boolean {
  return previewKindOf(file) === "markdown";
}
