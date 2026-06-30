"use client";

import { File, FileImage, FileText, Paperclip, UploadCloud, X } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { ContextBudget, type ContextSegment } from "@/components/composites/context-budget";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Spinner } from "@/components/ui/spinner";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { useSpace } from "@/features/spaces/use-space";
import { cn } from "@/lib/utils";
import { SaveRow } from "./general-section";
import { useUpdateAssistant, type Assistant } from "./use-assistant";

type Attachment = NonNullable<Assistant["attachments"]>[number];

const BYTES_PER_TOKEN = 4;

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(kb < 10 ? 1 : 0)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
}

const TYPE_LABELS: Record<string, string> = {
  "application/pdf": "PDF",
  "text/plain": "TXT",
  "text/markdown": "MD",
  "text/csv": "CSV",
  "application/json": "JSON",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "DOCX"
};

function fileTypeLabel(mimetype: string): string {
  if (TYPE_LABELS[mimetype]) return TYPE_LABELS[mimetype];
  const subtype = mimetype.split("/").pop() ?? mimetype;
  return (subtype.split(/[.+]/).pop() ?? subtype).toUpperCase().slice(0, 5);
}

function compactTokens(value: number): string {
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(
    Math.round(value)
  );
}

/** token_count is computed server-side; estimate from extracted text until it arrives. */
function attachmentTokens(file: Attachment): number {
  if (file.token_count != null) return file.token_count;
  if (file.transcription) return Math.ceil(file.transcription.length / BYTES_PER_TOKEN);
  return 0;
}

function FileIcon({ mimetype }: { mimetype: string }) {
  const className = "text-muted-foreground size-5 shrink-0";
  if (mimetype.startsWith("image/")) return <FileImage aria-hidden="true" className={className} />;
  if (mimetype === "application/pdf" || mimetype.startsWith("text/"))
    return <FileText aria-hidden="true" className={className} />;
  return <File aria-hidden="true" className={className} />;
}

/**
 * Assistant attachments: guideline files added to the assistant's context.
 * Files upload through the proxy (POST /files/) and their ids are saved on the
 * assistant; removing one here detaches it on save (the blob is not deleted).
 */
export function AttachmentsSection({ assistant }: { assistant: Assistant }) {
  const t = useTranslations();
  const format = useFormatter();
  const { space } = useSpace();
  const update = useUpdateAssistant(assistant.id);
  const fileInput = useRef<HTMLInputElement>(null);

  const saved: Attachment[] = assistant.attachments ?? [];
  const [files, setFiles] = useState<Attachment[]>(saved);
  const [uploading, setUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [preview, setPreview] = useState<Attachment | null>(null);

  const dirty =
    JSON.stringify(files.map((file) => file.id).sort()) !==
    JSON.stringify(saved.map((file) => file.id).sort());

  const totalSize = files.reduce((sum, file) => sum + (file.size ?? 0), 0);
  const promptTokens = Math.ceil((assistant.prompt?.text?.length ?? 0) / BYTES_PER_TOKEN);
  const filesTokens = files.reduce((sum, file) => sum + attachmentTokens(file), 0);
  const model =
    space.completion_models.find((candidate) => candidate.id === assistant.completion_model?.id) ??
    null;
  const maxTokens = model?.token_limit ?? null;

  const segments: ContextSegment[] = [
    { key: "prompt", label: t("prompt"), tokens: promptTokens, className: "bg-chart-1" },
    { key: "attachments", label: t("attachments"), tokens: filesTokens, className: "bg-chart-2" }
  ];

  function metaLine(file: Attachment): string {
    return [
      fileTypeLabel(file.mimetype),
      formatBytes(file.size),
      file.token_count != null ? `${compactTokens(file.token_count)} ${t("tokens")}` : null,
      file.created_at
        ? format.dateTime(new Date(file.created_at), { day: "numeric", month: "short" })
        : null
    ]
      .filter(Boolean)
      .join(" · ");
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
    <SettingsGroup title={t("attachments")}>
      <SettingsRow title={t("attachments")} description={t("attachments_description")}>
        <div className="flex flex-col gap-3">
          <ContextBudget segments={segments} maxTokens={maxTokens} />

          {files.length > 0 && (
            <div className="rounded-lg border">
              <div className="text-muted-foreground border-b px-3 py-2 text-xs">
                {[t("attachment_count", { count: files.length }), formatBytes(totalSize)].join(
                  " · "
                )}
              </div>
              <div className="max-h-72 overflow-y-auto">
                <ul>
                  {files.map((file) => (
                    <li
                      key={file.id}
                      className="flex items-center gap-2 border-b px-3 py-2 last:border-b-0"
                    >
                      <button
                        type="button"
                        onClick={() => setPreview(file)}
                        aria-label={`${t("preview")} ${file.name}`}
                        className="hover:bg-muted/50 -mx-1 flex min-w-0 flex-1 items-center gap-3 rounded px-1 py-0.5 text-left"
                      >
                        <FileIcon mimetype={file.mimetype} />
                        <span className="min-w-0">
                          <span className="block truncate text-sm">{file.name}</span>
                          <span className="text-muted-foreground block truncate text-xs">
                            {metaLine(file)}
                          </span>
                        </span>
                      </button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        aria-label={`${t("remove")} ${file.name}`}
                        onClick={() =>
                          setFiles((current) => current.filter((other) => other.id !== file.id))
                        }
                      >
                        <X className="size-4" />
                      </Button>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}

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
              "flex flex-col items-center gap-2 rounded-lg border border-dashed p-4 text-center",
              dragActive && "border-primary bg-muted/50"
            )}
          >
            <UploadCloud aria-hidden="true" className="text-muted-foreground size-5" />
            <p className="text-muted-foreground text-xs">
              {files.length > 0 ? t("drop_files_here") : t("no_attachments")}
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={uploading}
              onClick={() => fileInput.current?.click()}
            >
              {uploading ? <Spinner className="size-4" /> : <Paperclip className="size-4" />}
              {t("attach_files")}
            </Button>
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
        </div>
      </SettingsRow>

      <SaveRow
        dirty={dirty}
        pending={update.isPending}
        onSave={() => update.mutate({ attachments: files.map((file) => ({ id: file.id })) })}
        onRevert={() => setFiles(saved)}
      />

      <Dialog open={preview !== null} onOpenChange={(open) => !open && setPreview(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="truncate">{preview?.name}</DialogTitle>
            <DialogDescription>{preview ? metaLine(preview) : null}</DialogDescription>
          </DialogHeader>
          <p className="text-muted-foreground text-xs">{t("extracted_text")}</p>
          <div className="max-h-80 overflow-y-auto rounded-md border p-3">
            {preview?.transcription ? (
              <p className="text-sm whitespace-pre-wrap">{preview.transcription}</p>
            ) : (
              <p className="text-muted-foreground text-sm">{t("no_extracted_text")}</p>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </SettingsGroup>
  );
}
