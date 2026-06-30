"use client";

import {
  ArrowUpDown,
  Braces,
  Download,
  Eye,
  File,
  FileArchive,
  FileAudio,
  FileCode,
  FileImage,
  FileJson,
  FilePenLine,
  FileSpreadsheet,
  FileText,
  FileType,
  FileVideo,
  Paperclip,
  Search,
  Trash2,
  UploadCloud,
  type LucideIcon
} from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useMemo, useRef, useState } from "react";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useReportDirty } from "@/components/composites/save-status";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { AttachmentPreviewDialog, useSignedUrl } from "@/features/chat/attachments";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";
import { SaveRow } from "./general-section";
import { useUpdateAssistant, type Assistant } from "./use-assistant";

type Attachment = NonNullable<Assistant["attachments"]>[number];

const TYPE_LABELS: Record<string, string> = {
  "application/pdf": "PDF",
  "text/plain": "TXT",
  "text/markdown": "MD",
  "text/csv": "CSV",
  "application/json": "JSON",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "DOCX",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "XLSX",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PPTX",
  "application/vnd.ms-excel": "XLS",
  "application/vnd.ms-powerpoint": "PPT",
  "application/zip": "ZIP"
};

function fileExtension(name: string): string {
  return name.split(".").pop()?.toLowerCase() ?? "";
}

function attachmentTypeLabel(file: Attachment): string {
  const knownLabel = TYPE_LABELS[file.mimetype];
  if (knownLabel) return knownLabel;
  const extension = fileExtension(file.name);
  if (extension) return extension.toUpperCase().slice(0, 5);
  const subtype = file.mimetype.split("/").pop() ?? file.mimetype;
  return (subtype.split(/[.+]/).pop() ?? subtype).toUpperCase().slice(0, 5);
}

function compactTokens(value: number): string {
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(
    Math.round(value)
  );
}

function fileIconConfig(file: Attachment): {
  Icon: LucideIcon;
  className: string;
  label: string;
} {
  const extension = fileExtension(file.name);
  const type = file.mimetype;

  if (type === "application/pdf" || extension === "pdf") {
    return {
      Icon: FileText,
      className: "bg-red-50 text-red-600 dark:bg-red-950/50",
      label: "PDF"
    };
  }
  if (type.startsWith("image/")) {
    return {
      Icon: FileImage,
      className: "bg-sky-50 text-sky-600 dark:bg-sky-950/50",
      label: "IMG"
    };
  }
  if (type.startsWith("audio/")) {
    return {
      Icon: FileAudio,
      className: "bg-violet-50 text-violet-600 dark:bg-violet-950/50",
      label: "AUD"
    };
  }
  if (type.startsWith("video/")) {
    return {
      Icon: FileVideo,
      className: "bg-pink-50 text-pink-600 dark:bg-pink-950/50",
      label: "VID"
    };
  }
  if (
    type.includes("spreadsheet") ||
    type.includes("excel") ||
    ["csv", "xls", "xlsx"].includes(extension)
  ) {
    return {
      Icon: FileSpreadsheet,
      className: "bg-emerald-50 text-emerald-600 dark:bg-emerald-950/50",
      label: extension === "csv" ? "CSV" : "XLS"
    };
  }
  if (type.includes("presentation") || ["ppt", "pptx"].includes(extension)) {
    return {
      Icon: FileType,
      className: "bg-orange-50 text-orange-600 dark:bg-orange-950/50",
      label: "PPT"
    };
  }
  if (type.includes("wordprocessing") || ["doc", "docx"].includes(extension)) {
    return {
      Icon: FilePenLine,
      className: "bg-blue-50 text-blue-600 dark:bg-blue-950/50",
      label: "DOC"
    };
  }
  if (
    type.includes("zip") ||
    type.includes("compressed") ||
    ["zip", "7z", "rar", "tar", "gz"].includes(extension)
  ) {
    return {
      Icon: FileArchive,
      className: "bg-amber-50 text-amber-600 dark:bg-amber-950/50",
      label: "ZIP"
    };
  }
  if (type === "application/json" || extension === "json") {
    return {
      Icon: FileJson,
      className: "bg-lime-50 text-lime-700 dark:bg-lime-950/50",
      label: "JSON"
    };
  }
  if (
    [
      "js",
      "jsx",
      "ts",
      "tsx",
      "py",
      "java",
      "go",
      "rs",
      "html",
      "css",
      "xml",
      "sql",
      "yaml",
      "yml"
    ].includes(extension)
  ) {
    return {
      Icon: FileCode,
      className: "bg-indigo-50 text-indigo-600 dark:bg-indigo-950/50",
      label: "CODE"
    };
  }
  if (type.startsWith("text/")) {
    return {
      Icon: Braces,
      className: "bg-slate-100 text-slate-600 dark:bg-slate-800",
      label: "TXT"
    };
  }
  return {
    Icon: File,
    className: "bg-muted text-muted-foreground",
    label: attachmentTypeLabel(file)
  };
}

function AssistantAttachmentIcon({ file }: { file: Attachment }) {
  const { Icon, className, label } = fileIconConfig(file);

  return (
    <span
      aria-hidden="true"
      className={cn("relative grid size-10 shrink-0 place-items-center rounded-md", className)}
    >
      <Icon className="size-5" />
      <span className="bg-background/95 absolute right-0.5 bottom-0.5 rounded px-1 py-0.5 text-[8px] leading-none font-semibold shadow-sm">
        {label}
      </span>
    </span>
  );
}

function AttachmentPreview({ file, onClose }: { file: Attachment; onClose: () => void }) {
  const url = useSignedUrl(file.id);
  return (
    <AttachmentPreviewDialog
      open
      onOpenChange={(next) => !next && onClose()}
      name={file.name}
      mimetype={file.mimetype}
      url={url}
    />
  );
}

/**
 * Assistant attachments: guideline files added to the assistant's context.
 * Files upload through the proxy (POST /files/) and their ids are saved on the
 * assistant; removing one here detaches it on save (the blob is not deleted).
 */
export function AttachmentsSection({ assistant }: { assistant: Assistant }) {
  const t = useTranslations();
  const format = useFormatter();
  const update = useUpdateAssistant(assistant.id);
  const fileInput = useRef<HTMLInputElement>(null);

  const saved: Attachment[] = assistant.attachments ?? [];
  const [files, setFiles] = useState<Attachment[]>(saved);
  const [uploading, setUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [preview, setPreview] = useState<Attachment | null>(null);
  const [query, setQuery] = useState("");
  const [sortAscending, setSortAscending] = useState(true);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);

  const dirty =
    JSON.stringify(files.map((file) => file.id).sort()) !==
    JSON.stringify(saved.map((file) => file.id).sort());
  useReportDirty("attachments", dirty);

  const totalSize = files.reduce((sum, file) => sum + (file.size ?? 0), 0);

  const filteredFiles = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return files
      .filter((file) => {
        if (!needle) return true;
        return (
          file.name.toLowerCase().includes(needle) ||
          attachmentTypeLabel(file).toLowerCase().includes(needle)
        );
      })
      .sort((first, second) =>
        sortAscending
          ? first.name.localeCompare(second.name)
          : second.name.localeCompare(first.name)
      );
  }, [files, query, sortAscending]);

  function metaLine(file: Attachment): string {
    return [
      attachmentTypeLabel(file),
      formatBytes(file.size),
      file.token_count != null ? `${compactTokens(file.token_count)} ${t("tokens")}` : null,
      file.created_at
        ? format.dateTime(new Date(file.created_at), { day: "numeric", month: "short" })
        : null
    ]
      .filter(Boolean)
      .join(" · ");
  }

  async function downloadFile(file: Attachment) {
    setDownloadingId(file.id);
    try {
      const { url } = await unwrap(
        browserApi.POST("/api/v1/files/{id}/signed-url/", {
          params: { path: { id: file.id } },
          body: { expires_in: 3600, content_disposition: "attachment" }
        })
      );
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = file.name;
      anchor.rel = "noreferrer";
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
    } catch (error) {
      toastApiError(error, t);
    } finally {
      setDownloadingId(null);
    }
  }

  async function uploadFiles(selected: File[]) {
    if (selected.length === 0) return;
    setUploading(true);
    try {
      for (const file of selected) {
        const body = new FormData();
        body.append("upload_file", file);
        const uploaded = await unwrap(
          browserApi.POST("/api/v1/files/", {
            body: body as unknown as { upload_file: string },
            bodySerializer: (formData: unknown) => formData as FormData
          })
        );
        setFiles((current) => [
          ...current,
          {
            id: uploaded.id,
            name: uploaded.name ?? file.name,
            mimetype: uploaded.mimetype ?? file.type,
            size: uploaded.size ?? file.size,
            created_at: uploaded.created_at ?? null,
            token_count: uploaded.token_count ?? null,
            transcription: uploaded.transcription ?? null
          }
        ]);
      }
    } catch (error) {
      toastApiError(error, t);
    } finally {
      setUploading(false);
    }
  }

  return (
    <SettingsGroup
      title={t("attachments")}
      description={t("attachments_description")}
      headerEnd={
        <>
          <span className="bg-secondary text-secondary-foreground rounded-full px-2.5 py-1 text-xs font-medium">
            {t("attachment_count", { count: files.length })}
          </span>
          <span className="bg-secondary text-secondary-foreground rounded-full px-2.5 py-1 text-xs font-medium">
            {t("total_size", { size: formatBytes(totalSize) })}
          </span>
        </>
      }
    >
      <SettingsRow>
        <div className="bg-card flex flex-col gap-4 rounded-lg border p-4">
          <div className="flex flex-col gap-2 sm:flex-row">
            <div className="relative min-w-0 flex-1">
              <Search
                aria-hidden="true"
                className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
              />
              <Input
                value={query}
                placeholder={t("search_attachments")}
                className="pl-9"
                onChange={(event) => setQuery(event.target.value)}
              />
            </div>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                className="shrink-0"
                onClick={() => setSortAscending((value) => !value)}
              >
                <ArrowUpDown className="size-4" />
                {t("name")}
              </Button>
            </div>
          </div>

          <div className="-mx-4">
            {filteredFiles.length > 0 ? (
              <ul className="max-h-80 overflow-y-auto">
                {filteredFiles.map((file) => (
                  <li
                    key={file.id}
                    className="hover:bg-muted/40 flex items-center gap-3 border-t px-4 py-3"
                  >
                    <AssistantAttachmentIcon file={file} />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{file.name}</p>
                      <p className="text-muted-foreground truncate text-xs">{metaLine(file)}</p>
                    </div>
                    <div className="flex items-center gap-1">
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        aria-label={`${t("preview")} ${file.name}`}
                        onClick={() => setPreview(file)}
                      >
                        <Eye className="size-4" />
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        aria-label={`${t("download")} ${file.name}`}
                        disabled={downloadingId === file.id}
                        onClick={() => void downloadFile(file)}
                      >
                        {downloadingId === file.id ? (
                          <Spinner className="size-4" />
                        ) : (
                          <Download className="size-4" />
                        )}
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        aria-label={`${t("remove")} ${file.name}`}
                        onClick={() =>
                          setFiles((current) => current.filter((other) => other.id !== file.id))
                        }
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="text-muted-foreground flex min-h-24 items-center justify-center px-3 py-6 text-sm">
                {query ? t("no_results") : t("no_attachments")}
              </div>
            )}
          </div>

          <div
            onDragOver={(event) => {
              event.preventDefault();
              setDragActive(true);
            }}
            onDragLeave={() => setDragActive(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragActive(false);
              void uploadFiles(Array.from(event.dataTransfer.files));
            }}
            className={cn(
              "flex min-h-28 flex-col items-center justify-center gap-3 rounded-lg border border-dashed px-4 py-5 text-center",
              dragActive && "border-primary bg-primary/5"
            )}
          >
            <span className="bg-muted grid size-10 place-items-center rounded-full">
              <UploadCloud aria-hidden="true" className="text-muted-foreground size-5" />
            </span>
            <p className="text-sm font-medium">
              {uploading ? t("uploading") : t("drop_files_here")}
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="shrink-0"
              disabled={uploading}
              onClick={() => fileInput.current?.click()}
            >
              {uploading ? <Spinner className="size-4" /> : <Paperclip className="size-4" />}
              {t("attach_files")}
            </Button>
          </div>

          <input
            ref={fileInput}
            type="file"
            multiple
            hidden
            aria-label={t("attach_files")}
            onChange={(event) => {
              void uploadFiles(Array.from(event.target.files ?? []));
              event.target.value = "";
            }}
          />
        </div>
      </SettingsRow>

      <SaveRow
        dirty={dirty}
        pending={update.isPending}
        onSave={() => update.mutate({ attachments: files.map((file) => ({ id: file.id })) })}
        onRevert={() => setFiles(saved)}
      />

      {preview && <AttachmentPreview file={preview} onClose={() => setPreview(null)} />}
    </SettingsGroup>
  );
}
