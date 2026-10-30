"use client";

import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { FileInput } from "@astryxdesign/core/FileInput";
import { IconButton } from "@astryxdesign/core/IconButton";
import { ProgressBar } from "@astryxdesign/core/ProgressBar";
import { CircleAlert, CircleCheck, Download, RotateCw, X } from "lucide-react";
import { useLocale, useTranslations } from "use-intl";
import { formatBytes } from "@/lib/format";
import { UploadRetryHint } from "./recording/upload-retry-hint";
import type { InputProblem, UploadEntry } from "./run-contract";
import { inputLimitsText } from "./run-format";
import type { RuntimeInput } from "./runs-api";

/** The id of the element around a step's files, for "go to the problem". */
export function inputAnchorId(formId: string, stepId: string): string {
  return `${formId}-input-${stepId}`;
}

export function inputLabel(input: RuntimeInput, t: ReturnType<typeof useTranslations>): string {
  return input.label?.trim() || t("flow_runs_input_label_unnamed", { order: input.step_order });
}

export function inputProblemText(
  input: RuntimeInput,
  problem: InputProblem,
  t: ReturnType<typeof useTranslations>
): string {
  const label = inputLabel(input, t);
  switch (problem) {
    case "required":
      return t("flow_runs_input_required", { input: label });
    case "too_many":
      return t("flow_runs_input_too_many", { input: label, count: input.max_files ?? 0 });
    case "uploading":
      return t("flow_runs_input_uploading", { input: label });
    case "failed":
      return t("flow_runs_input_failed", { input: label });
  }
}

/** Hands a file the form keeps to the person, as a download. */
export function saveFile(file: File) {
  const url = URL.createObjectURL(file);
  const link = document.createElement("a");
  link.href = url;
  link.download = file.name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

function UploadRow({
  entry,
  onRemove,
  onRetry,
  onSave
}: {
  entry: UploadEntry;
  onRemove: () => void;
  onRetry: (() => void) | null;
  onSave: (() => void) | null;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const percent = Math.round((entry.progress ?? 0) * 100);
  return (
    <li className="border-ax-border flex items-start gap-3 border-t py-2 first:border-t-0">
      <span className="mt-0.5 shrink-0" aria-hidden="true">
        {entry.state === "done" ? (
          <CircleCheck className="text-ax-success size-4" />
        ) : entry.state === "failed" ? (
          <CircleAlert className="text-ax-error size-4" />
        ) : null}
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="text-ax-text text-sm break-words">{entry.name}</span>
        <span className="text-ax-text-secondary text-xs">
          {entry.state === "uploading"
            ? t("flow_runs_upload_progress", { percent, size: formatBytes(entry.size, locale) })
            : entry.state === "done"
              ? t("flow_runs_upload_done", { size: formatBytes(entry.size, locale) })
              : null}
        </span>
        {entry.state === "uploading" ? (
          <ProgressBar
            label={t("flow_runs_upload_progress_label", { name: entry.name })}
            isLabelHidden
            value={percent}
            max={100}
          />
        ) : null}
        {entry.state === "failed" && entry.problem ? (
          <span className="text-ax-error text-xs">{entry.problem}</span>
        ) : null}
        {entry.state === "failed" && entry.retryable && entry.recording ? (
          <span className="text-ax-text-secondary text-xs">
            <UploadRetryHint nextRetryAt={entry.nextRetryAt} />
          </span>
        ) : null}
      </span>
      {onRetry ? (
        <IconButton
          label={t("flow_transcript_upload_retry", { name: entry.name })}
          icon={<RotateCw aria-hidden="true" />}
          variant="ghost"
          size="sm"
          onClick={onRetry}
        />
      ) : null}
      {onSave ? (
        <IconButton
          label={t("flow_transcript_upload_save", { name: entry.name })}
          icon={<Download aria-hidden="true" />}
          variant="ghost"
          size="sm"
          onClick={onSave}
        />
      ) : null}
      <IconButton
        label={
          entry.state === "uploading"
            ? t("flow_runs_upload_stop", { name: entry.name })
            : t("flow_runs_upload_remove", { name: entry.name })
        }
        icon={<X aria-hidden="true" />}
        variant="ghost"
        size="sm"
        onClick={onRemove}
      />
    </li>
  );
}

/**
 * The files one step takes: a drop zone with "Välj filer", what the step
 * accepts, and each picked file with its upload state and a way to take it
 * off. A step whose audio files may be the parts of one recording offers
 * that choice once it has more than one.
 */
export function RunFileInput({
  formId,
  input,
  entries,
  message,
  onAdd,
  onRemove,
  onRetry,
  fileOf,
  singleRecording,
  recorder
}: {
  formId: string;
  input: RuntimeInput;
  entries: readonly UploadEntry[];
  message: string | null;
  onAdd: (files: File[]) => void;
  onRemove: (key: string) => void;
  /** Sends a failed file again. */
  onRetry?: (key: string) => void;
  /** The file the form keeps for an entry, which the person may save. */
  fileOf?: (key: string) => File | null;
  singleRecording: { offered: boolean; value: boolean; onChange: (value: boolean) => void };
  /** Records the step's audio instead of picking files. */
  recorder?: React.ReactNode;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const label = inputLabel(input, t);
  const limits = inputLimitsText(input, t, locale);
  const description = [input.description?.trim(), limits].filter(Boolean).join(" ");
  const multiple = input.max_files == null || input.max_files > 1;

  return (
    <div id={inputAnchorId(formId, input.step_id)} className="flex flex-col gap-2">
      <FileInput
        label={label}
        description={description || undefined}
        value={null}
        onChange={(files) => {
          const picked = Array.isArray(files) ? files : files ? [files] : [];
          if (picked.length > 0) onAdd(picked);
        }}
        accept={(input.accepted_mimetypes ?? []).join(",") || undefined}
        isMultiple={multiple}
        mode="dropzone"
        placeholder={
          multiple ? t("flow_runs_input_choose_files") : t("flow_runs_input_choose_file")
        }
        status={message ? { type: "error", message } : undefined}
        statusVariant="detached"
        width="100%"
        {...(input.required ? { isRequired: true } : { isOptional: true })}
      />
      {recorder}
      {entries.length > 0 ? (
        <ul aria-label={t("flow_runs_input_files_label", { input: label })} className="m-0 p-0">
          {entries.map((entry) => (
            <UploadRow
              key={entry.key}
              entry={entry}
              onRemove={() => onRemove(entry.key)}
              onRetry={
                entry.state === "failed" && entry.retryable && onRetry
                  ? () => onRetry(entry.key)
                  : null
              }
              onSave={
                entry.recording && fileOf
                  ? () => {
                      const file = fileOf(entry.key);
                      if (file) saveFile(file);
                    }
                  : null
              }
            />
          ))}
        </ul>
      ) : null}
      {singleRecording.offered ? (
        <CheckboxInput
          label={t("flow_runs_single_recording")}
          description={t("flow_runs_single_recording_hint")}
          value={singleRecording.value}
          onChange={singleRecording.onChange}
        />
      ) : null}
    </div>
  );
}
