"use client";

import { useJobEventsConnected } from "@/features/jobs/job-events";
import { Button } from "@astryxdesign/core/Button";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { useQuery, useSuspenseQuery } from "@tanstack/react-query";
import { Check, ChevronLeft, Copy, Download } from "lucide-react";
import Link from "@/lib/link";
import { useTranslations } from "use-intl";
import { useId, useState } from "react";
import { Streamdown } from "streamdown";
import { LoadingState } from "@/components/composites/loading-state";
import { PageHeader } from "@/components/composites/page-header";
import { DockedActions } from "@/components/shell/docked-actions";
import { browserApi } from "@/lib/api/browser";
import { pollWhile } from "@/lib/api/query";
import { useCopy } from "@/lib/hooks/use-copy";
import { ClientTime } from "@/components/composites/client-time";
import {
  saveBlob,
  saveUrl,
  signedFileUrl,
  toastDownloadError
} from "@/features/files/signed-file-url";
import { appRunQueryOptions, getResultTitle, isRunActive, type AppRun } from "../apps";
import { AppRunStatusToken } from "../status-token";

const RESULT_POLL_MS = 3_000;

type ResultTab = "results" | "transcription";

function resultTitleLabels(t: (key: string) => string) {
  return { inputPrefix: t("input"), empty: t("app_run_no_input_title") };
}

function saveText(text: string, fileName: string) {
  saveBlob(new Blob([text], { type: "text/plain;charset=utf-8" }), fileName);
}

/**
 * Kopiera and Ladda ner for the run's output: the page's own actions, docked
 * with Ny körning on a phone and in the page header from 768 px.
 */
function OutputActions({ text, fileName }: { text: string; fileName: string }) {
  const t = useTranslations();
  const { copy, isCopied } = useCopy();
  return (
    <>
      <Button
        label={isCopied ? t("copied") : t("copy")}
        icon={
          isCopied ? (
            <Check className="size-4" aria-hidden="true" />
          ) : (
            <Copy className="size-4" aria-hidden="true" />
          )
        }
        onClick={() => void copy(text)}
      />
      <Button
        label={t("download")}
        icon={<Download className="size-4" aria-hidden="true" />}
        onClick={() => saveText(text, fileName)}
      />
    </>
  );
}

function RunOutput({ run }: { run: AppRun }) {
  const t = useTranslations();
  if (!run.output) {
    return <p className="text-muted-foreground text-center">{t("no_output_generated")}</p>;
  }
  return <Streamdown>{run.output}</Streamdown>;
}

/** A run still queued or running: what happens, and that leaving is safe. */
function PendingResult() {
  const t = useTranslations();
  return (
    <div className="flex flex-col gap-1">
      <p className="font-semibold">{t("result_being_generated")}</p>
      <p className="text-muted-foreground text-sm">{t("app_result_leave_hint")}</p>
      <div data-result-skeleton="" aria-hidden="true" className="flex flex-col gap-3 pt-5">
        <LoadingState variant="text" rows={7} />
      </div>
    </div>
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
            try {
              saveUrl(await signedFileUrl(browserApi, file.id, "attachment"), file.name);
            } catch (error) {
              toastDownloadError(error, t);
            }
          }}
        />
      ))}
    </div>
  );
}

function TranscriptionTab({ run }: { run: AppRun }) {
  const transcribed = run.input.files.filter((file) => file.transcription);
  const { data: urls = {} } = useQuery({
    // Outside the "app-runs" prefix a finished job refreshes: signing again
    // would swap the players' sources and stop an audio mid-playback.
    queryKey: ["app-run-audio-urls", run.id],
    queryFn: async (): Promise<Record<string, string>> => {
      const entries = await Promise.all(
        transcribed.map(
          async (file) => [file.id, await signedFileUrl(browserApi, file.id, "inline")] as const
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
                onClick={() => saveText(file.transcription ?? "", `${file.name}.txt`)}
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
 * audio players stop and the signed audio URLs load on first view. The page
 * holds the open tab: its Kopiera and Ladda ner act on the output, so they
 * show only while the output does.
 */
function ResultTabs({
  run,
  tab,
  onTabChange
}: {
  run: AppRun;
  tab: ResultTab;
  onTabChange: (tab: ResultTab) => void;
}) {
  const t = useTranslations();
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
        onChange={(value) => onTabChange(value === "transcription" ? "transcription" : "results")}
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
      {panel("results", <RunOutput run={run} />)}
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
  // The job feed refreshes app runs when they finish; poll only while it is down.
  const live = useJobEventsConnected();
  const { data: run } = useSuspenseQuery({
    ...appRunQueryOptions(browserApi, runId),
    refetchInterval: pollWhile((run) => !live && !!run && isRunActive(run.status), RESULT_POLL_MS)
  });

  const complete = !isRunActive(run.status);
  const transcribedCount = run.input.files.filter((file) => file.transcription).length;
  const [tab, setTab] = useState<ResultTab>("results");
  const outputShown = transcribedCount === 0 || tab === "results";
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
              <DockedActions label={t("app_result_actions")}>
                {complete && run.output && outputShown && (
                  <OutputActions text={run.output} fileName={outputFileName} />
                )}
                <Button href={newRunHref} variant="primary" label={t("new_run")} />
              </DockedActions>
            </>
          }
        />
      </div>

      {/* The summary comes first, so a phone shows the status above the
          result; from 1024 px it is the column on the right. */}
      <div className="flex flex-col gap-8 lg:flex-row-reverse lg:items-start">
        <aside className="flex w-full flex-col gap-3 lg:sticky lg:top-6 lg:w-64">
          <div className="flex">
            <AppRunStatusToken status={run.status} />
          </div>
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
          {/* One line for all the files, so a phone's summary stays short above
              the result however many there are. */}
          {run.input.files.length > 0 && (
            <div className="border-border flex justify-between gap-4 border-b pb-1">
              <span>{t("input")}</span>
              <span className="min-w-0 text-end text-sm break-words">
                {run.input.files.map((file) => file.name).join(", ")}
              </span>
            </div>
          )}
        </aside>

        {/* A card from 768 px; on a phone the result runs flat on the page. */}
        <div className="md:border-border md:bg-card w-full flex-1 md:min-h-72 md:rounded-lg md:border md:p-6 md:shadow-sm lg:p-10">
          {!complete ? (
            <PendingResult />
          ) : transcribedCount > 0 ? (
            <ResultTabs run={run} tab={tab} onTabChange={setTab} />
          ) : run.output ? (
            <RunOutput run={run} />
          ) : run.status === "failed" && run.input.files.length > 0 ? (
            <FailedFileDownloads run={run} />
          ) : (
            <p className="text-muted-foreground text-center">{t("no_outputs_generated")}</p>
          )}
        </div>
      </div>
    </div>
  );
}
