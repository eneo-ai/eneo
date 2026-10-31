"use client";

import { useMutation } from "@tanstack/react-query";
import { AppWindow, Play, Upload } from "lucide-react";
import { useRouter } from "@/lib/navigation";
import { useTranslations } from "use-intl";
import { useEffect, useState } from "react";
import { useAnnounce } from "@astryxdesign/core/hooks";
import {
  FieldProblem,
  fieldProblemProps,
  revealProblems
} from "@/components/composites/field-problem";
import { iconUrl } from "@/components/composites/icon-field";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { useJobs } from "@/features/jobs/use-jobs";
import type { App } from "../apps";
import { AppInputs } from "./app-inputs";
import { releasePreviews } from "@/features/files/use-file-uploads";
import { useAppRunInputs, type RunFile } from "./use-app-run";
import { useFileDrop } from "@/features/files/use-file-drop";
import { inputFieldRules } from "@/features/files/upload-plan";

/**
 * The "run" surface of an app: its identity, the dynamic input form, and a
 * submit that creates a run and forwards to the result page.
 */
export function RunView({ app, resultHref }: { app: App; resultHref: (runId: string) => string }) {
  const t = useTranslations();
  const router = useRouter();
  const { trackJob } = useJobs();
  const inputs = useAppRunInputs();

  const icon = iconUrl(app.icon_id);
  const hasModel = app.completion_model !== null && app.completion_model !== undefined;
  const dropField = app.input_fields.find((field) =>
    ["text-upload", "audio-upload", "image-upload"].includes(field.type)
  );
  const { dragging, handlers } = useFileDrop(
    (files) => {
      if (hasModel && dropField) void inputs.addFiles(files, inputFieldRules(dropField));
    },
    { enabled: hasModel && dropField !== undefined }
  );
  const announce = useAnnounce();
  useEffect(() => {
    if (dragging) announce(t("drop_files_here_upload", { appName: app.name }));
  }, [dragging, announce, t, app.name]);

  const run = useMutation({
    mutationFn: ({ files, text }: { files: RunFile[]; text: string }) =>
      unwrap(
        browserApi.POST("/api/v1/apps/{id}/runs/", {
          params: { path: { id: app.id } },
          body: {
            files: files.flatMap((file) => (file.fileId ? [{ id: file.fileId }] : [])),
            text: text.trim() || null
          }
        })
      ),
    onSuccess: (created, submittedInputs) => {
      trackJob();
      releasePreviews(submittedInputs.files);
      inputs.setText((current) => (current === submittedInputs.text ? "" : current));
      router.push(resultHref(created.id));
    },
    onError: (error, submittedInputs) => {
      inputs.restoreFiles(submittedInputs.files);
      toastApiError(error, t);
    }
  });

  const [submitted, setSubmitted] = useState(false);
  const [waitNoticed, setWaitNoticed] = useState(false);
  const inputProblem = submitted && !inputs.hasInput ? t("input_data_required_tooltip") : null;

  // Submit is never disabled: without input the problem shows at the inputs,
  // and focus moves to the first; while files upload, it asks to wait.
  function submit() {
    if (run.isPending) return;
    if (!inputs.hasInput) {
      revealProblems(
        () => setSubmitted(true),
        document.getElementById("app-run-inputs")?.querySelector<HTMLElement>("textarea, button")
      );
      return;
    }
    if (inputs.uploading) {
      setWaitNoticed(true);
      return;
    }
    setWaitNoticed(false);
    run.mutate({ files: inputs.detachFiles(), text: inputs.text });
  }

  return (
    <div className="flex w-full flex-1 flex-col items-center justify-center p-4" {...handlers}>
      {dragging && (
        <div className="bg-ax-surface border-ax-accent pointer-events-none fixed inset-0 z-50 flex flex-col items-center justify-center gap-4 border-2 p-6 text-center">
          <Upload className="text-ax-text-secondary size-10" />
          <p className="max-w-full text-xl font-semibold break-words">
            {t("drop_files_here_upload", { appName: app.name })}
          </p>
        </div>
      )}
      <div className="border-border bg-card flex w-full max-w-[64ch] flex-col gap-4 rounded-xl border p-4 shadow-lg">
        <div className="flex flex-col items-center gap-3 pt-2">
          <span className="bg-muted text-muted-foreground flex size-16 items-center justify-center overflow-hidden rounded-2xl">
            {icon ? (
              <img src={icon} alt="" className="size-full object-cover" />
            ) : (
              <AppWindow className="size-8" />
            )}
          </span>
          <h2 className="text-center text-2xl font-extrabold">{app.name}</h2>
          {app.description && (
            <p className="text-muted-foreground max-w-[50ch] text-center text-sm">
              {app.description}
            </p>
          )}
        </div>

        {hasModel ? (
          <>
            <div
              id="app-run-inputs"
              role="group"
              aria-label={t("input")}
              className="bg-muted/40 flex min-h-[12rem] w-full flex-col items-center justify-center gap-4 rounded-lg border p-6"
              {...fieldProblemProps("app-run-inputs", inputProblem)}
            >
              <AppInputs app={app} inputs={inputs} />
            </div>
            <FieldProblem id="app-run-inputs" problem={inputProblem} />
            <div>
              {/* Never disabled: busy, it keeps focus and a second press is ignored. */}
              <Button
                size="lg"
                className="w-full"
                aria-busy={run.isPending || undefined}
                onClick={submit}
              >
                <Play className="size-4" />
                {run.isPending ? t("submitting") : t("submit")}
              </Button>
              {/* Always rendered, so the notice is announced when it appears. */}
              <p role="status" className="text-muted-foreground mt-2 text-sm empty:mt-0">
                {waitNoticed && inputs.uploading ? t("form_wait_for_uploads") : ""}
              </p>
            </div>
          </>
        ) : (
          <div className="bg-muted/40 flex min-h-[12rem] w-full items-center justify-center rounded-lg border p-6 opacity-60">
            <p className="text-muted-foreground max-w-[50ch] text-center text-sm">
              {t("no_completion_model_description")}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
