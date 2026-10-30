"use client";

import { Button } from "@astryxdesign/core/Button";
import { Download, FileText } from "lucide-react";
import { useLocale, useTranslations } from "use-intl";
import { useState } from "react";
import { EneoApiError } from "@/lib/api/errors";
import { formatBytes } from "@/lib/format";
import { toast } from "@/lib/toast";
import type { StepInputFile } from "./run-format";
import { refusalText } from "./run-messages";
import { artifactDownloadPath, inputFileDownloadPath, type RunResultFile } from "./runs-api";

/** Saves a file through a short-lived signed link; the server names it. */
function save(path: string, name?: string) {
  Object.assign(document.createElement("a"), { href: path, download: name ?? "" }).click();
}

/** Says why a download link could not be made, with the trace id for support. */
function downloadFailed(error: unknown, t: ReturnType<typeof useTranslations>) {
  const traceId = error instanceof EneoApiError ? error.traceId : undefined;
  toast.error(refusalText(error, t), {
    description: traceId ? `Trace ID: ${traceId}` : undefined
  });
}

/** A download button that asks the core for a fresh signed link on each press. */
function DownloadButton({
  label,
  visible,
  getPath,
  name
}: {
  label: string;
  visible: string;
  getPath: () => Promise<string>;
  name?: string;
}) {
  const t = useTranslations();
  const [pending, setPending] = useState(false);
  return (
    <Button
      label={label}
      icon={<Download aria-hidden="true" />}
      size="sm"
      isLoading={pending}
      isInterruptible
      onClick={async () => {
        if (pending) return;
        setPending(true);
        try {
          save(await getPath(), name);
        } catch (error) {
          downloadFailed(error, t);
        } finally {
          setPending(false);
        }
      }}
    >
      {visible}
    </Button>
  );
}

function FileRow({ flowId, runId, file }: { flowId: string; runId: string; file: RunResultFile }) {
  const t = useTranslations();
  const locale = useLocale();
  const purged = file.availability === "content_purged";
  return (
    <li className="border-ax-border flex flex-wrap items-center gap-3 border-t py-2 first:border-t-0">
      <FileText className="text-ax-text-secondary size-4 shrink-0" aria-hidden="true" />
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="text-ax-text text-sm break-words">{file.name}</span>
        <span className="text-ax-text-secondary text-xs">
          {purged ? t("flow_runs_file_purged") : formatBytes(file.size, locale)}
        </span>
      </span>
      {purged ? null : (
        <DownloadButton
          label={t("flow_runs_file_download", { name: file.name })}
          visible={t("flow_runs_file_download_short")}
          getPath={() => artifactDownloadPath(flowId, runId, file.file_id)}
          name={file.name}
        />
      )}
    </li>
  );
}

/**
 * Files a run or one of its steps produced, each with a download through a
 * signed link the core mints per request (and audits). A file whose content
 * retention removed says so instead of offering a link that would fail.
 */
export function RunFiles({
  flowId,
  runId,
  files,
  label
}: {
  flowId: string;
  runId: string;
  files: readonly RunResultFile[];
  label: string;
}) {
  if (files.length === 0) return null;
  return (
    <ul aria-label={label} className="m-0 flex flex-col p-0">
      {[...files]
        .sort((a, b) => a.ordinal - b.ordinal)
        .map((file) => (
          <FileRow key={file.file_id} flowId={flowId} runId={runId} file={file} />
        ))}
    </ul>
  );
}

/**
 * The files a step received, by name and type, each with a download. A file
 * the step result does not name is numbered instead.
 */
export function RunInputFiles({
  flowId,
  runId,
  files,
  label
}: {
  flowId: string;
  runId: string;
  files: readonly StepInputFile[];
  label: string;
}) {
  const t = useTranslations();
  if (files.length === 0) return null;
  return (
    <ul aria-label={label} className="m-0 flex flex-col p-0">
      {files.map((file, index) => (
        <li
          key={file.fileId}
          className="border-ax-border flex flex-wrap items-center gap-3 border-t py-2 first:border-t-0"
        >
          <FileText className="text-ax-text-secondary size-4 shrink-0" aria-hidden="true" />
          <span className="flex min-w-0 flex-1 flex-col">
            <span className="text-ax-text text-sm break-words">
              {file.name ?? t("flow_runs_input_file_short", { number: index + 1 })}
            </span>
            {file.typeName ? (
              <span className="text-ax-text-secondary text-xs">{file.typeName}</span>
            ) : null}
          </span>
          <DownloadButton
            label={
              file.name
                ? t("flow_runs_file_download", { name: file.name })
                : t("flow_runs_input_file_download", { number: index + 1 })
            }
            visible={t("flow_runs_file_download_short")}
            getPath={() => inputFileDownloadPath(flowId, runId, file.fileId)}
            name={file.name ?? undefined}
          />
        </li>
      ))}
    </ul>
  );
}
