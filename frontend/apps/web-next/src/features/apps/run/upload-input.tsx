"use client";

import { Loader2, Upload, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";
import { inputFieldRules, type InputField } from "../apps";
import type { RunFile } from "./use-app-run";

const MIME_FRIENDLY: Record<string, string> = {
  "text/plain": "TXT",
  "text/markdown": "Markdown",
  "text/csv": "CSV",
  "application/csv": "CSV",
  "application/pdf": "PDF",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PowerPoint",
  "image/png": "PNG",
  "image/jpeg": "JPEG",
  "audio/mpeg": "MP3",
  "audio/mp3": "MP3",
  "audio/wav": "WAV",
  "audio/ogg": "OGG",
  "audio/webm": "WebM",
  "audio/mp4": "M4A",
  "audio/x-m4a": "M4A",
  "video/mp4": "MP4"
};

function friendlyType(mime: string): string {
  const trimmed = mime.trim().toLowerCase();
  if (MIME_FRIENDLY[trimmed]) return MIME_FRIENDLY[trimmed];
  const subtype = trimmed.split("/")[1]?.split(";")[0] ?? trimmed;
  return subtype.toUpperCase();
}

export function FileChip({ file, onRemove }: { file: RunFile; onRemove?: () => void }) {
  return (
    <div className="border-border bg-background flex items-center gap-2 rounded-lg border px-3 py-2">
      {file.uploading ? (
        <Loader2 className="text-muted-foreground size-4 shrink-0 animate-spin" />
      ) : null}
      <span className="min-w-0 flex-1 truncate text-sm">{file.name}</span>
      <span className="text-muted-foreground shrink-0 text-xs">{formatBytes(file.size)}</span>
      {onRemove && (
        <Button variant="ghost" size="icon" className="size-6 shrink-0" onClick={onRemove}>
          <X className="size-4" />
        </Button>
      )}
    </div>
  );
}

/** Drag/drop + click file picker for an upload-type app input. */
export function UploadInput({
  field,
  description,
  files,
  onAddFiles,
  onRemoveFile
}: {
  field: InputField;
  description?: string | null;
  files: RunFile[];
  onAddFiles: (files: File[], rules: ReturnType<typeof inputFieldRules>) => void;
  onRemoveFile: (key: string) => void;
}) {
  const t = useTranslations();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const rules = inputFieldRules(field);

  const acceptedLabel = [
    ...new Set(rules.perTypeLimits.map((limit) => friendlyType(limit.mimetype)))
  ]
    .slice(0, 6)
    .join(", ");
  const atCapacity = files.length >= rules.maxFiles;

  return (
    <div className="flex w-full max-w-[60ch] flex-col items-center gap-3">
      {files.length > 0 && (
        <div className="flex w-full flex-col gap-2">
          {files.map((file) => (
            <FileChip key={file.key} file={file} onRemove={() => onRemoveFile(file.key)} />
          ))}
        </div>
      )}

      {!atCapacity && (
        <button
          type="button"
          className={cn(
            "border-border bg-muted/40 hover:border-primary/50 hover:bg-muted flex w-full cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed p-6 transition-colors",
            dragging && "border-primary bg-muted"
          )}
          onClick={() => inputRef.current?.click()}
          onDragEnter={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragging(false);
          }}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            const dropped = Array.from(event.dataTransfer.files);
            if (dropped.length > 0) onAddFiles(dropped, rules);
          }}
        >
          <Upload className="text-muted-foreground size-5" />
          <span className="text-sm font-medium">
            {description || t("upload_files_description")}
          </span>
          {acceptedLabel && <span className="text-muted-foreground text-xs">{acceptedLabel}</span>}
        </button>
      )}

      <input
        ref={inputRef}
        type="file"
        multiple
        accept={rules.acceptString || undefined}
        className="hidden"
        onChange={(event) => {
          const selected = Array.from(event.target.files ?? []);
          if (selected.length > 0) onAddFiles(selected, rules);
          event.target.value = "";
        }}
      />
    </div>
  );
}
