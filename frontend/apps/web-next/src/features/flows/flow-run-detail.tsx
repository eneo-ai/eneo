"use client";

import { Button } from "@astryxdesign/core/Button";
import { Token } from "@astryxdesign/core/Token";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Ban,
  Check,
  CheckCircle2,
  ChevronRight,
  Clock,
  LoaderCircle,
  Pause,
  SkipForward,
  X,
  XCircle,
  type LucideIcon
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import type { ReactNode } from "react";
import { ANSWER_TEXT_CLASS, MessageResponse } from "@/components/ai-elements/message";
import { ClientTime } from "@/components/composites/client-time";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { StatusLabel } from "@/components/composites/status-label";
import { formatSeconds } from "@/features/chat/format";
import { toastApiError } from "@/lib/api/toast";
import { cn } from "@/lib/utils";
import {
  runDisplayName,
  runStatusLabel,
  runStatusTone,
  runVersionLabel,
  stepKindLabel,
  stepStatusLabel
} from "./flow-labels";
import { FlowReviewActions } from "./flow-review-actions";
import { FlowRunFiles } from "./flow-run-files";
import { type StepTranscription } from "./flow-transcript";
import { FlowRunTranscript } from "./flow-transcript-editor";
import {
  cancelFlowRun,
  flowKeys,
  flowRunQueryOptions,
  isActiveRun,
  isOpenCheckpoint
} from "./flows";
import {
  formFieldsOf,
  type FlowDefinition,
  type FlowRunPublic,
  type FlowRunStepPublic,
  type StepResultStatus
} from "./types";

const STEP_ICON: Record<StepResultStatus, { icon: LucideIcon; className: string; spin?: boolean }> =
  {
    pending: { icon: Clock, className: "bg-ax-muted text-ax-text-secondary" },
    running: {
      icon: LoaderCircle,
      className: "bg-ax-accent-muted text-ax-text-accent",
      spin: true
    },
    awaiting_review: { icon: Pause, className: "bg-ax-warning-muted text-ax-warning" },
    completed: { icon: Check, className: "bg-ax-success-muted text-ax-success" },
    failed: { icon: X, className: "bg-ax-error-muted text-ax-error" },
    cancelled: { icon: Ban, className: "bg-ax-muted text-ax-text-secondary" },
    skipped: { icon: SkipForward, className: "bg-ax-muted text-ax-text-secondary" }
  };

const PREVIEW_CHARS = 90;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/** The text a payload reads as: its text, else its value or the whole thing as JSON. */
function payloadText(payload: Record<string, unknown>): string {
  if (payload.value != null) return JSON.stringify(payload.value, null, 2);
  if (typeof payload.text === "string") return payload.text;
  return JSON.stringify(payload, null, 2);
}

/** One line of a payload, for a collapsed row. */
function previewOf(payload: Record<string, unknown> | null | undefined): string | null {
  if (!payload || Object.keys(payload).length === 0) return null;
  const text = payloadText(payload).replace(/\s+/g, " ").trim();
  if (!text) return null;
  return text.length > PREVIEW_CHARS ? `${text.slice(0, PREVIEW_CHARS - 1)}…` : text;
}

/**
 * A step's payload as it reads best: Markdown for text, pretty JSON for a
 * value or anything else. Kept small; the row it sits in is closed by default.
 */
function Payload({ payload }: { payload: Record<string, unknown> }) {
  // A step's output is {text, value}: the parsed value when the step produced
  // JSON (the text is its serialisation), else the text, which reads as
  // Markdown. Any other payload (a step's rendered input) shows as it is.
  const markdown =
    payload.value == null &&
    typeof payload.text === "string" &&
    Object.keys(payload).every((key) =>
      [
        "text",
        "value",
        "file_ids",
        "sources",
        "coverage",
        "processing_calls",
        "words_read",
        "words_answered"
      ].includes(key)
    );
  return (
    <div className="bg-ax-sunken rounded-ax-inner max-h-56 overflow-auto px-2.5 py-2">
      {markdown ? (
        <MessageResponse className={cn(ANSWER_TEXT_CLASS, "text-[12.5px] leading-normal")}>
          {payload.text as string}
        </MessageResponse>
      ) : (
        <pre className="m-0 font-mono text-[12px] leading-normal break-words whitespace-pre-wrap">
          {payloadText(payload)}
        </pre>
      )}
    </div>
  );
}

/**
 * A compact disclosure row: a small label with a chevron, a one-line
 * preview while closed, the content below when open. Native details, so it
 * is keyboard-operable and announced without any script.
 */
function Disclosure({
  label,
  preview,
  defaultOpen = false,
  children
}: {
  label: string;
  preview?: string | null;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  return (
    <details open={defaultOpen || undefined} className="group min-w-0">
      <summary className="text-ax-text-secondary hover:text-ax-text focus-visible:outline-ring rounded-ax-inner -ms-1 flex min-h-6 cursor-pointer list-none items-center gap-1 px-1 text-xs focus-visible:outline-2 focus-visible:outline-offset-1 [&::-webkit-details-marker]:hidden">
        <ChevronRight
          aria-hidden="true"
          className="size-3.5 shrink-0 transition-transform group-open:rotate-90"
        />
        <span className="shrink-0 font-semibold">{label}</span>
        {preview && (
          <span className="min-w-0 truncate font-normal group-open:hidden" aria-hidden="true">
            · {preview}
          </span>
        )}
      </summary>
      <div className="pt-1 pb-1">{children}</div>
    </details>
  );
}

function durationOf(
  start: string | null | undefined,
  end: string | null | undefined,
  locale: string
): string | null {
  if (!start || !end) return null;
  const ms = new Date(end).getTime() - new Date(start).getTime();
  return ms > 0 ? formatSeconds(ms, locale) : null;
}

function RunStep({
  step,
  flowId,
  run
}: {
  step: FlowRunStepPublic;
  flowId: string;
  run: FlowRunPublic;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const { icon: Icon, className, spin } = STEP_ICON[step.status] ?? STEP_ICON.pending;
  const duration = durationOf(step.started_at, step.finished_at, locale);
  const input = isRecord(step.input_payload_json) ? step.input_payload_json : null;
  const output = isRecord(step.output_payload_json) ? step.output_payload_json : null;
  const files = step.result_files ?? [];
  const detail = [
    stepKindLabel(step.kind, t),
    stepStatusLabel(step.status, t),
    duration,
    step.num_tokens_output ? t("flow_step_tokens", { count: step.num_tokens_output }) : null
  ]
    .filter(Boolean)
    .join(" · ");
  const inputPreview = previewOf(input);
  const outputPreview = previewOf(output);
  // A transcribe step keeps its transcript with its input; show it as turns.
  const transcription =
    step.kind === "transcribe" && isRecord(input?.transcription)
      ? (input!.transcription as StepTranscription)
      : null;
  // The files the step was given, named through the run's own file list.
  const readIds = Array.isArray(input?.file_ids) ? (input!.file_ids as unknown[]) : [];
  const readFiles = [...(run.input_files ?? []), ...(run.result_files ?? [])].filter((file) =>
    readIds.includes(file.id)
  );

  return (
    <li className="relative flex gap-3 ps-1">
      <span
        aria-hidden="true"
        className={cn(
          "relative z-10 mt-0.5 flex size-[22px] shrink-0 items-center justify-center rounded-full",
          className
        )}
      >
        <Icon className={cn("size-[13px]", spin && "motion-safe:animate-spin")} />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1 pb-3">
        <div className="flex flex-col leading-snug">
          <span className="text-[13px] font-semibold">
            {step.step_order + 1} · {step.name}
          </span>
          <span className="text-ax-text-secondary text-xs">{detail}</span>
        </div>
        {step.error_message && (
          <p className="text-ax-error m-0 text-[13px]">
            {step.error_code ? `${step.error_code}: ` : ""}
            {step.error_message}
          </p>
        )}
        {files.length > 0 && (
          <FlowRunFiles
            flowId={flowId}
            runId={run.id}
            files={files}
            label={t("flow_step_files_label")}
          />
        )}
        {inputPreview && input && (
          <Disclosure label={t("flow_step_show_input")} preview={inputPreview}>
            <div className="flex flex-col gap-1.5">
              {readFiles.length > 0 && (
                <FlowRunFiles
                  flowId={flowId}
                  runId={run.id}
                  files={readFiles}
                  label={t("flow_step_read_files")}
                />
              )}
              <Payload payload={input} />
            </div>
          </Disclosure>
        )}
        {transcription ? (
          <Disclosure label={t("flow_step_show_transcript")} preview={outputPreview}>
            <div className="bg-ax-sunken rounded-ax-inner max-h-96 overflow-auto px-2.5 py-2">
              <FlowRunTranscript flowId={flowId} runId={run.id} stepId={step.step_id} />
            </div>
          </Disclosure>
        ) : (
          outputPreview &&
          output && (
            <Disclosure label={t("flow_step_show_output")} preview={outputPreview}>
              <Payload payload={output} />
            </Disclosure>
          )
        )}
        {output && Array.isArray(output.sources) && (
          <div className="text-ax-text-secondary flex flex-col gap-1 text-xs">
            <p className="m-0">
              {t("flow_processing_coverage", {
                sources: output.sources.length,
                calls: Number(output.processing_calls ?? 0),
                read: Number(output.words_read ?? 0),
                answered: Number(output.words_answered ?? 0)
              })}
            </p>
            <ul className="m-0 list-disc ps-4">
              {output.sources.filter(isRecord).map((source, index) => (
                <li key={index}>
                  [{String(source.source_id)}] {String(source.name)}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </li>
  );
}

function RunInputs({
  run,
  flowId,
  definition
}: {
  run: FlowRunPublic;
  flowId: string;
  definition: FlowDefinition | null;
}) {
  const t = useTranslations();
  const values = Object.entries(run.input_payload_json ?? {}).filter(
    ([, value]) => value != null && value !== ""
  );
  const files = run.input_files ?? [];
  if (values.length === 0 && files.length === 0) return null;
  const labelOf = (key: string) =>
    (definition ? formFieldsOf(definition) : []).find((field) => field.key === key)?.label ?? key;
  const preview = [
    ...values.map(
      ([key, value]) =>
        `${labelOf(key)}: ${typeof value === "string" ? value : JSON.stringify(value)}`
    ),
    ...files.map((file) => file.name)
  ].join(", ");
  return (
    <Disclosure label={t("flow_run_inputs")} preview={preview} defaultOpen>
      <div className="flex flex-col gap-1.5">
        {values.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {values.map(([key, value]) => (
              <Token
                key={key}
                size="sm"
                label={`${labelOf(key)}: ${typeof value === "string" ? value : JSON.stringify(value)}`}
              />
            ))}
          </div>
        )}
        <FlowRunFiles
          flowId={flowId}
          runId={run.id}
          files={files}
          label={t("flow_run_input_files")}
        />
      </div>
    </Disclosure>
  );
}

/** The last step that produced something (a review step repeats what it reviewed). */
function finalStep(run: FlowRunPublic): FlowRunStepPublic | null {
  const steps = run.steps ?? [];
  for (let index = steps.length - 1; index >= 0; index--) {
    const step = steps[index]!;
    if (step.kind !== "review" && step.status === "completed") return step;
  }
  return null;
}

/**
 * What the run came to: for a finished run its files and final output as
 * the thing to take away, for a paused run the decision to make, for a
 * failed or cancelled run what stopped it. The steps below are the account
 * of how it got there.
 */
function RunOutcome({ run, flowId }: { run: FlowRunPublic; flowId: string }) {
  const t = useTranslations();
  const locale = useLocale();
  const files = run.result_files ?? [];
  const steps = run.steps ?? [];
  const checkpoint = run.review_checkpoint;

  if (run.status === "completed") {
    const last = finalStep(run);
    const output = last && isRecord(last.output_payload_json) ? last.output_payload_json : null;
    // A document step's text is its filename; the file chips already say that.
    const text = output && files.length === 0 ? previewOf(output) && payloadText(output) : null;
    const duration = durationOf(run.started_at, run.finished_at, locale);
    return (
      <section
        aria-labelledby="flow-run-outcome-heading"
        className="border-ax-success/40 bg-ax-success-muted/40 rounded-ax-container flex flex-col gap-3 border p-3"
      >
        <div className="flex items-start gap-2">
          <CheckCircle2 aria-hidden="true" className="text-ax-success mt-0.5 size-5 shrink-0" />
          <div className="flex min-w-0 flex-col">
            <h4 id="flow-run-outcome-heading" className="m-0 text-sm font-semibold">
              {t("flow_run_done_title")}
            </h4>
            <span className="text-ax-text-secondary text-xs">
              {t("flow_run_done_detail", { count: steps.length })}
              {duration ? ` · ${duration}` : ""}
            </span>
          </div>
        </div>
        {files.length > 0 && (
          <div className="flex flex-col gap-1">
            <span className="text-ax-text-secondary text-[11px] font-semibold tracking-wide uppercase">
              {t("flow_run_artifacts")}
            </span>
            <FlowRunFiles
              flowId={flowId}
              runId={run.id}
              files={files}
              label={t("flow_run_artifacts")}
            />
          </div>
        )}
        {text && (
          <div className="flex flex-col gap-1">
            <span className="text-ax-text-secondary text-[11px] font-semibold tracking-wide uppercase">
              {t("flow_run_final_output")}
            </span>
            <div className="bg-ax-surface rounded-ax-inner max-h-72 overflow-auto px-3 py-2">
              {output?.value != null ? (
                <pre className="m-0 font-mono text-[12px] leading-normal break-words whitespace-pre-wrap">
                  {text}
                </pre>
              ) : (
                <MessageResponse className={cn(ANSWER_TEXT_CLASS, "text-[13px] leading-normal")}>
                  {text}
                </MessageResponse>
              )}
            </div>
          </div>
        )}
      </section>
    );
  }

  if (run.status === "awaiting_review" && checkpoint && isOpenCheckpoint(checkpoint)) {
    const step = steps.find((candidate) => candidate.step_id === checkpoint.step_id);
    return (
      <section
        aria-labelledby="flow-run-outcome-heading"
        className="border-ax-warning/40 bg-ax-warning-muted/40 rounded-ax-container flex flex-col gap-3 border p-3"
      >
        <div className="flex items-start gap-2">
          <Pause aria-hidden="true" className="text-ax-warning mt-0.5 size-5 shrink-0" />
          <h4 id="flow-run-outcome-heading" className="m-0 text-sm font-semibold">
            {t("flow_run_awaiting_title", { step: step?.name ?? "" })}
          </h4>
        </div>
        <FlowReviewActions flowId={flowId} runId={run.id} checkpoint={checkpoint} />
      </section>
    );
  }

  if (run.status === "failed" || run.status === "cancelled") {
    const failed = run.status === "failed";
    return (
      <section
        aria-labelledby="flow-run-outcome-heading"
        role={failed ? "alert" : undefined}
        className={cn(
          "rounded-ax-container flex items-start gap-2 border p-3",
          failed ? "border-ax-error/40 bg-ax-error-muted/40" : "border-ax-border bg-ax-muted"
        )}
      >
        {failed ? (
          <XCircle aria-hidden="true" className="text-ax-error mt-0.5 size-5 shrink-0" />
        ) : (
          <Ban aria-hidden="true" className="text-ax-text-secondary mt-0.5 size-5 shrink-0" />
        )}
        <div className="flex min-w-0 flex-col gap-0.5">
          <h4 id="flow-run-outcome-heading" className="m-0 text-sm font-semibold">
            {failed ? t("flow_run_failed_title") : t("flow_run_cancelled_title")}
          </h4>
          {run.error && (
            <p className={cn("m-0 text-[13px]", failed && "text-ax-error")}>
              {run.error.code ? `${run.error.code}: ` : ""}
              {run.error.message}
            </p>
          )}
        </div>
      </section>
    );
  }

  // Queued or running: where it stands.
  const current = steps.find((step) => step.status === "running" || step.status === "pending");
  return (
    <p className="text-ax-text-secondary m-0 text-[13px]">
      {current
        ? t("flow_run_progress", {
            current: current.step_order + 1,
            total: steps.length,
            name: current.name
          })
        : runStatusLabel(run.status, t)}
    </p>
  );
}

/**
 * One run: what it came to (files, final output, a waiting review or the
 * error) first, then what it was started with and every step with its
 * timing, closed payloads and files. Polled while active; a cancel while it
 * can still be stopped.
 */
export function FlowRunDetail({
  flowId,
  runId,
  definition,
  onBack
}: {
  flowId: string;
  runId: string;
  /** The flow's definition, to name the inputs; null while it loads. */
  definition: FlowDefinition | null;
  onBack: () => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const run = useQuery(flowRunQueryOptions(flowId, runId));
  const cancel = useMutation({
    mutationFn: () => cancelFlowRun(flowId, runId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: flowKeys.run(flowId, runId) });
      void queryClient.invalidateQueries({ queryKey: flowKeys.runs(flowId) });
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <div className="flex flex-col gap-4 p-4">
      <Button
        label={t("flow_runs_back")}
        variant="ghost"
        size="sm"
        className="-ms-2 self-start"
        onClick={onBack}
      />
      <QueryStateBoundary query={run} rows={4}>
        {(data) => (
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="flex min-w-0 flex-col gap-1">
                <h3 className="m-0 text-sm font-semibold">
                  {t("flow_run_title", { name: runDisplayName(data) })}
                </h3>
                <span className="text-ax-text-secondary text-xs">
                  <ClientTime value={data.created_at} format="date_time" />
                  {" · "}
                  {runVersionLabel(data, t)}
                  {data.principal_type === "service" && <> · {t("flow_run_by_service")}</>}
                </span>
                <StatusLabel
                  status={runStatusTone(data.status)}
                  label={runStatusLabel(data.status, t)}
                  isPulsing={data.status === "running"}
                  className="text-xs"
                />
              </div>
              {isActiveRun(data.status) && (
                <Button
                  label={t("flow_run_cancel")}
                  variant="destructive"
                  size="sm"
                  isLoading={cancel.isPending}
                  isInterruptible
                  onClick={() => {
                    if (!cancel.isPending) cancel.mutate();
                  }}
                />
              )}
            </div>
            <RunOutcome run={data} flowId={flowId} />
            <RunInputs run={data} flowId={flowId} definition={definition} />
            <section aria-labelledby="flow-run-steps-heading" className="flex flex-col gap-2">
              <h4
                id="flow-run-steps-heading"
                className="text-ax-text-secondary m-0 text-[11px] font-semibold tracking-wide uppercase"
              >
                {t("flow_section_steps")}
              </h4>
              <ol className="before:bg-ax-border relative m-0 flex list-none flex-col p-0 before:absolute before:start-[14px] before:top-3 before:bottom-6 before:w-px">
                {(data.steps ?? []).map((step) => (
                  <RunStep key={step.step_id} step={step} flowId={flowId} run={data} />
                ))}
              </ol>
            </section>
          </div>
        )}
      </QueryStateBoundary>
    </div>
  );
}
