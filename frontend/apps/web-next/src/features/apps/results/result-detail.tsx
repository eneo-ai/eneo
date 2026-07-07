"use client";

import { useQuery, useSuspenseQuery } from "@tanstack/react-query";
import { ChevronLeft, Copy, Download } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { Streamdown } from "streamdown";
import { PageHeader } from "@/components/composites/page-header";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { browserApi } from "@/lib/api/browser";
import { formatDateTime } from "@/lib/format";
import {
  appRunQueryOptions,
  fileSignedUrl,
  getResultTitle,
  isRunActive,
  type AppRun
} from "../apps";
import { AppRunStatusBadge } from "../status-badge";

const RESULT_POLL_MS = 3_000;

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
  return (
    <div className="flex justify-end gap-1">
      <Button
        variant="ghost"
        size="sm"
        onClick={() => {
          void navigator.clipboard.writeText(text);
          toast.success(t("copied"));
        }}
      >
        <Copy className="size-4" /> {t("copy")}
      </Button>
      <Button variant="ghost" size="sm" onClick={() => downloadText(text, fileName)}>
        <Download className="size-4" /> {t("download")}
      </Button>
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
          variant="outline"
          onClick={async () => {
            const url = await fileSignedUrl(browserApi, file.id, "attachment");
            window.open(url, "_blank");
          }}
        >
          <Download className="size-4" /> {t("download")} &quot;{file.name}&quot;
        </Button>
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
                onClick={() => downloadText(file.transcription ?? "", `${file.name}.txt`)}
              >
                <Download className="size-4" /> {t("download")}
              </Button>
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
        <PageHeader title={title}>
          {editHref && (
            <Button asChild variant="outline">
              <Link href={editHref}>{t("edit")}</Link>
            </Button>
          )}
          <Button asChild>
            <Link href={newRunHref}>{t("new_run")}</Link>
          </Button>
        </PageHeader>
      </div>

      <div className="flex flex-col gap-8 lg:flex-row lg:items-start">
        <div className="border-border bg-card min-h-72 w-full flex-1 rounded-lg border p-6 shadow-sm lg:p-10">
          {!complete ? (
            <div className="flex h-64 flex-col items-center justify-center gap-3">
              <span className="border-primary size-8 animate-spin rounded-full border-2 border-t-transparent" />
              <span className="text-muted-foreground">{t("result_being_generated")}</span>
            </div>
          ) : transcribedCount > 0 ? (
            <Tabs defaultValue="results">
              <TabsList>
                <TabsTrigger value="results">{t("results")}</TabsTrigger>
                <TabsTrigger value="transcription">{t("transcription")}</TabsTrigger>
              </TabsList>
              <TabsContent value="results" className="pt-4">
                {run.output ? (
                  <>
                    <OutputToolbar text={run.output} fileName={outputFileName} />
                    <Streamdown>{run.output}</Streamdown>
                  </>
                ) : (
                  <p className="text-muted-foreground text-center">{t("no_output_generated")}</p>
                )}
              </TabsContent>
              <TabsContent value="transcription" className="pt-4">
                <TranscriptionTab run={run} />
              </TabsContent>
            </Tabs>
          ) : run.output ? (
            <>
              <OutputToolbar text={run.output} fileName={outputFileName} />
              <Streamdown>{run.output}</Streamdown>
            </>
          ) : run.status === "failed" && run.input.files.length > 0 ? (
            <FailedFileDownloads run={run} />
          ) : (
            <p className="text-muted-foreground text-center">{t("no_outputs_generated")}</p>
          )}
        </div>

        <aside className="flex w-full flex-col gap-3 lg:sticky lg:top-6 lg:w-64">
          <div className="border-border flex items-center justify-between border-b pb-1">
            <span>{t("started")}</span>
            <span className="font-mono text-sm">{formatDateTime(run.created_at)}</span>
          </div>
          {complete && (
            <div className="border-border flex items-center justify-between border-b pb-1">
              <span>{t("finished")}</span>
              <span className="font-mono text-sm">{formatDateTime(run.finished_at)}</span>
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
