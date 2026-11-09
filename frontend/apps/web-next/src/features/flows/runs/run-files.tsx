import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Download, FileText } from "lucide-react";
import { useLocale, useTranslations } from "use-intl";
import { useState } from "react";
import { saveUrl, toastDownloadError } from "@/features/files/signed-file-url";
import { formatBytes } from "@/lib/format";
import type { StepInputFile } from "./run-format";
import { refusalText } from "./run-messages";
import { artifactDownloadPath, inputFileDownloadPath, type RunResultFile } from "./runs-api";

/** A download button that asks the core for a fresh signed link on each press. */
export function DownloadButton({
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
          // Through a short-lived signed link; without a name the server names the file.
          saveUrl(await getPath(), name ?? "");
        } catch (error) {
          // Why the link could not be made, in the flow catalog's words, with the support ids.
          toastDownloadError(error, t, { message: refusalText(error, t) });
        } finally {
          setPending(false);
        }
      }}
    >
      {visible}
    </Button>
  );
}

/** A file's ending as a short type tag ("pdf", "docx"), when its name has one. */
function fileEnding(name: string | null | undefined): string | null {
  const ending = name?.match(/\.([a-z0-9]{1,5})$/i)?.[1];
  return ending ? ending.toLowerCase() : null;
}

/**
 * A file's name with its type as a tag beside it. The tag repeats the name's
 * ending, so it is for the eye only.
 */
function FileName({ name, ending }: { name: string; ending: string | null }) {
  return (
    <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
      <span className="text-ax-text min-w-0 text-sm [overflow-wrap:anywhere]">{name}</span>
      {ending ? <Badge variant="blue" label={ending} aria-hidden="true" /> : null}
    </span>
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
        <FileName name={file.name} ending={fileEnding(file.name)} />
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
      {files.map((file, index) => {
        const ending = fileEnding(file.name);
        return (
          <li
            key={file.fileId}
            className="border-ax-border flex flex-wrap items-center gap-3 border-t py-2 first:border-t-0"
          >
            <FileText className="text-ax-text-secondary size-4 shrink-0" aria-hidden="true" />
            <span className="flex min-w-0 flex-1 flex-col">
              <FileName
                name={file.name ?? t("flow_runs_input_file_short", { number: index + 1 })}
                ending={ending}
              />
              {/* The tag says the type when the name has an ending; else the type's name does. */}
              {file.typeName && !ending ? (
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
        );
      })}
    </ul>
  );
}
