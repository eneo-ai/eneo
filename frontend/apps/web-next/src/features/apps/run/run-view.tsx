"use client";

import { useMutation } from "@tanstack/react-query";
import { AppWindow, Play } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { flushSync } from "react-dom";
import { FieldProblem, fieldProblemProps } from "@/components/composites/field-problem";
import { iconUrl } from "@/components/composites/icon-field";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { useJobs } from "@/features/jobs/use-jobs";
import type { App } from "../apps";
import { AppInputs } from "./app-inputs";
import { useAppRunInputs } from "./use-app-run";

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

  const run = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/apps/{id}/runs/", {
          params: { path: { id: app.id } },
          body: {
            files: inputs.fileIds.map((id) => ({ id })),
            text: inputs.text.trim() || null
          }
        })
      ),
    onSuccess: (created) => {
      trackJob();
      inputs.clear();
      router.push(resultHref(created.id));
    },
    onError: (error) => toastApiError(error, t)
  });

  const [submitted, setSubmitted] = useState(false);
  const [waitNoticed, setWaitNoticed] = useState(false);
  const inputProblem = submitted && !inputs.hasInput ? t("input_data_required_tooltip") : null;

  // Submit is never disabled: without input the problem shows at the inputs,
  // and focus moves to the first; while files upload, it asks to wait.
  function submit() {
    if (run.isPending) return;
    if (!inputs.hasInput) {
      // Rendered before focus moves, so the input is read with the problem.
      flushSync(() => setSubmitted(true));
      document
        .getElementById("app-run-inputs")
        ?.querySelector<HTMLElement>("textarea, button")
        ?.focus();
      return;
    }
    if (inputs.uploading) {
      setWaitNoticed(true);
      return;
    }
    setWaitNoticed(false);
    run.mutate();
  }

  return (
    <div className="flex w-full flex-1 flex-col items-center justify-center p-4">
      <div className="border-border bg-card flex w-full max-w-[64ch] flex-col gap-4 rounded-xl border p-4 shadow-lg">
        <div className="flex flex-col items-center gap-3 pt-2">
          <span className="bg-muted text-muted-foreground flex size-16 items-center justify-center overflow-hidden rounded-2xl">
            {icon ? (
              // Auth-proxied backend upload; next/image cannot optimize it.
              // eslint-disable-next-line @next/next/no-img-element
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
