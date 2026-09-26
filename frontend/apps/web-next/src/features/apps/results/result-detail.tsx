"use client";

import { Button } from "@astryxdesign/core/Button";
import { useClipboard } from "@astryxdesign/core/hooks";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { useQuery, useSuspenseQuery } from "@tanstack/react-query";
import { Check, ChevronLeft, Copy, Download } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { Streamdown } from "streamdown";
import { PageHeader } from "@/components/composites/page-header";
import { browserApi } from "@/lib/api/browser";
import { toast } from "@/lib/toast";
import { ClientTime } from "@/components/composites/client-time";
import {
  appRunQueryOptions,
  fileSignedUrl,
  getResultTitle,
  isRunActive,
  type AppRun
} from "../apps";
import { AppRunStatusBadge } from "../status-badge";

const RESULT_POLL_MS = 3_000;

type ResultTab = "results" | "transcription";

function resultTitleLabels(t: (key: string) => string) {
  return { inputPrefix: t("input"), empty: t("app_run_no_input_title") };
}

function downloadText(text: string, fileName: string) {
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const anchor = document.createElement("a");
  anchor.href = URL.createObjectURL(blob);
  anchor.download = fileName;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(anchor.href), 1500);
}

function OutputToolbar({ text, fileName }: { text: string; fileName: string }) {
  const t = useTranslations();
  const { copy, isCopied } = useClipboard({ announce: t("copied_to_clipboard") });
  return (
    <div className="flex justify-end gap-1">
      <Button
        variant="ghost"
        size="sm"
        label={isCopied ? t("copied") : t("copy")}
        icon={
          isCopied ? (
            <Check className="size-4" aria-hidden="true" />
          ) : (
            <Copy className="size-4" aria-hidden="true" />
          )
        }
        onClick={async () => {
          if (!(await copy(text))) toast.error(t("chat_copy_failed"));
        }}
      />
      <Button
        variant="ghost"
        size="sm"
        label={t("download")}
        icon={<Download className="size-4" aria-hidden="true" />}
        onClick={() => downloadText(text, fileName)}
      />
    </div>
  );
}

function RunOutput({ run, fileName }: { run: AppRun; fileName: string }) {
  const t = useTranslations();
  if (!run.output) {
    return <p className="text-muted-foreground text-center">{t("no_output_generated")}</p>;
  }
  return (
    <>
      <OutputToolbar text={run.output} fileName={fileName} />
      <Streamdown>{run.output}</Streamdown>
    </>
  );
}

function FailedFileDownloads({ run }: { run: AppRun }) {
  const t = useTranslations();
  return (
    <div className="flex flex-col items-center gap-2">
      <p className="py-2">{t("app_run_failed_files_list")}</p>
      {run.input.files.map((file) => (
        <Button
          key={file.id}
          label={`${t("download")} "${file.name}"`}
          icon={<Download className="size-4" aria-hidden="true" />}
          onClick={async () => {
            const url = await fileSignedUrl(browserApi, file.id, "attachment");
            window.open(url, "_blank");
          }}
        />
      ))}
    </div>
  );
}

function TranscriptionTab({ run }: { run: AppRun }) {
  const transcribed = run.input.files.filter((file) => file.transcription);
  const { data: urls = {} } = useQuery({
    queryKey: ["app-runs", run.id, "audio-urls"],
    queryFn: async (): Promise<Record<string, string>> => {
      const entries = await Promise.all(
        transcribed.map(
          async (file) => [file.id, await fileSignedUrl(browserApi, file.id, "inline")] as const
        )
      );
      return Object.fromEntries(entries);
    },
    enabled: transcribed.length > 0
  });
  const t = useTranslations();

  return (
    <div className="flex flex-col gap-8">
      {transcribed.map((file) => (
        <div key={file.id} className="border-border bg-muted/40 rounded-xl border">
          <div className="border-border flex items-center justify-between gap-4 border-b p-3">
            <span className="truncate text-sm font-medium">{file.name}</span>
            {file.transcription && (
              <Button
                variant="ghost"
                size="sm"
                label={t("download")}
                icon={<Download className="size-4" aria-hidden="true" />}
                onClick={() => downloadText(file.transcription ?? "", `${file.name}.txt`)}
              />
            )}
          </div>
          {urls[file.id] && <audio controls src={urls[file.id]} className="w-full px-3 py-2" />}
          <div className="p-4">
            <Streamdown>{file.transcription ?? ""}</Streamdown>
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * The output and the input's transcriptions as WAI-ARIA tabs: the arrow keys
 * move between the tabs (TabList's roving focus), Enter or Space opens one,
 * and each panel is named by its tab. Only the open panel renders, so the
 * audio players stop and the signed audio URLs load on first view.
 */
function ResultTabs({ run, fileName }: { run: AppRun; fileName: string }) {
  const t = useTranslations();
  const [tab, setTab] = useState<ResultTab>("results");
  const baseId = useId();
  const tabId = (value: ResultTab) => `${baseId}-tab-${value}`;
  const panelId = (value: ResultTab) => `${baseId}-panel-${value}`;

  const panel = (value: ResultTab, content: React.ReactNode) => (
    <div
      role="tabpanel"
      id={panelId(value)}
      aria-labelledby={tabId(value)}
      hidden={tab !== value}
      // In the tab order, as the tabs pattern asks when a panel does not start
      // with a focusable element (the transcription panel starts with a name).
      tabIndex={0}
      className="focus-visible:outline-ring rounded-ax-element pt-4 focus-visible:outline-2 focus-visible:outline-offset-4"
    >
      {tab === value ? content : null}
    </div>
  );

  return (
    <div className="flex flex-col">
      <TabList
        role="tablist"
        aria-label={t("legacy_result_tabs_label")}
        value={tab}
        onChange={(value) => setTab(value === "transcription" ? "transcription" : "results")}
        hasDivider
      >
        <Tab
          id={tabId("results")}
          value="results"
          label={t("results")}
          panelId={panelId("results")}
        />
        <Tab
          id={tabId("transcription")}
          value="transcription"
          label={t("transcription")}
          panelId={panelId("transcription")}
        />
      </TabList>
      {panel("results", <RunOutput run={run} fileName={fileName} />)}
      {panel("transcription", <TranscriptionTab run={run} />)}
    </div>
  );
}

/**
 * One app run's result. Polls while the run is still producing output
 * (the Svelte app's app_run_updates websocket is replaced by polling).
 */
export function ResultDetail({
  runId,
  backHref,
  editHref,
  newRunHref
}: {
  runId: string;
  backHref: string;
  editHref?: string;
  newRunHref: string;
}) {
  const t = useTranslations();
  const { data: run } = useSuspenseQuery({
    ...appRunQueryOptions(browserApi, runId),
    refetchInterval: (query) =>
      query.state.data && isRunActive(query.state.data.status) ? RESULT_POLL_MS : false
  });

  const complete = !isRunActive(run.status);
  const transcribedCount = run.input.files.filter((file) => file.transcription).length;
  const title = getResultTitle(run, resultTitleLabels(t));
  const outputFileName = `${title.slice(0, 40)}.txt`;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <div className="flex flex-col gap-1">
        <Link
          href={backHref}
          className="text-muted-foreground hover:text-foreground flex w-fit items-center gap-1 text-sm"
        >
          <ChevronLeft className="size-4" />
          {t("back")}
        </Link>
        <PageHeader
          title={title}
          actions={
            <>
              {editHref && <Button href={editHref} label={t("edit")} />}
              <Button href={newRunHref} variant="primary" label={t("new_run")} />
            </>
          }
        />
      </div>

      <div className="flex flex-col gap-8 lg:flex-row lg:items-start">
        <div className="border-border bg-card min-h-72 w-full flex-1 rounded-lg border p-6 shadow-sm lg:p-10">
          {!complete ? (
            <div className="flex h-64 flex-col items-center justify-center gap-3">
              <span className="border-primary size-8 animate-spin rounded-full border-2 border-t-transparent" />
              <span className="text-muted-foreground">{t("result_being_generated")}</span>
            </div>
          ) : transcribedCount > 0 ? (
            <ResultTabs run={run} fileName={outputFileName} />
          ) : run.output ? (
            <RunOutput run={run} fileName={outputFileName} />
          ) : run.status === "failed" && run.input.files.length > 0 ? (
            <FailedFileDownloads run={run} />
          ) : (
            <p className="text-muted-foreground text-center">{t("no_outputs_generated")}</p>
          )}
        </div>

        <aside className="flex w-full flex-col gap-3 lg:sticky lg:top-6 lg:w-64">
          <div className="border-border flex items-center justify-between border-b pb-1">
            <span>{t("started")}</span>
            <span className="text-sm">
              {run.created_at ? <ClientTime value={run.created_at} format="date_time" /> : "—"}
            </span>
          </div>
          {complete && (
            <div className="border-border flex items-center justify-between border-b pb-1">
              <span>{t("finished")}</span>
              <span className="text-sm">
                {run.finished_at ? <ClientTime value={run.finished_at} format="date_time" /> : "—"}
              </span>
            </div>
          )}
          <AppRunStatusBadge status={run.status} variant="full" />
          {run.input.files.map((file) => (
            <div
              key={file.id}
              className="border-border bg-card flex items-center gap-2 rounded-lg border px-3 py-2 text-sm shadow-sm"
            >
              <span className="truncate">{file.name}</span>
            </div>
          ))}
        </aside>
      </div>
    </div>
  );
}
