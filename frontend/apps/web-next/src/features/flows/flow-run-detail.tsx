"use client";

import { Button } from "@astryxdesign/core/Button";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Ban,
  Check,
  Clock,
  LoaderCircle,
  Pause,
  SkipForward,
  X,
  type LucideIcon
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { ANSWER_TEXT_CLASS, MessageResponse } from "@/components/ai-elements/message";
import { ClientTime } from "@/components/composites/client-time";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { StatusLabel } from "@/components/composites/status-label";
import { formatSeconds } from "@/features/chat/format";
import { toastApiError } from "@/lib/api/toast";
import { cn } from "@/lib/utils";
import { Chip, Field, MonoBlock } from "./flow-fields";
import {
  runDisplayName,
  runStatusLabel,
  runStatusTone,
  stepKindLabel,
  stepStatusLabel
} from "./flow-labels";
import { FlowReviewActions } from "./flow-review-actions";
import { FlowRunFiles } from "./flow-run-files";
import {
  cancelFlowRun,
  flowKeys,
  flowRunQueryOptions,
  isActiveRun,
  isOpenCheckpoint
} from "./flows";
import type { FlowDefinition, FlowRunPublic, FlowRunStepPublic, StepResultStatus } from "./types";

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

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/**
 * A step's payload as it reads best: Markdown for text, pretty JSON for a
 * value or anything else. Nothing for an empty payload.
 */
function Payload({ payload }: { payload: Record<string, unknown> | null | undefined }) {
  if (!payload || Object.keys(payload).length === 0) return null;
  if (typeof payload.text === "string" && Object.keys(payload).length === 1) {
    return (
      <div className="bg-ax-sunken rounded-ax-inner max-h-96 overflow-auto px-3 py-2">
        <MessageResponse className={cn(ANSWER_TEXT_CLASS, "text-[13.5px] leading-normal")}>
          {payload.text}
        </MessageResponse>
      </div>
    );
  }
  const value = "value" in payload && Object.keys(payload).length === 1 ? payload.value : payload;
  return <MonoBlock>{JSON.stringify(value, null, 2)}</MonoBlock>;
}

function durationOf(step: FlowRunStepPublic, locale: string): string | null {
  if (!step.started_at || !step.finished_at) return null;
  const ms = new Date(step.finished_at).getTime() - new Date(step.started_at).getTime();
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
  const duration = durationOf(step, locale);
  const checkpoint = run.review_checkpoint;
  const reviewing =
    step.status === "awaiting_review" &&
    checkpoint?.step_id === step.step_id &&
    isOpenCheckpoint(checkpoint);
  const hasInput =
    isRecord(step.input_payload_json) && Object.keys(step.input_payload_json).length > 0;
  const hasOutput =
    isRecord(step.output_payload_json) && Object.keys(step.output_payload_json).length > 0;
  const files = step.result_files ?? [];
  const detail = [
    stepKindLabel(step.kind, t),
    stepStatusLabel(step.status, t),
    duration,
    step.num_tokens_output ? t("flow_step_tokens", { count: step.num_tokens_output }) : null
  ]
    .filter(Boolean)
    .join(" · ");

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
      <div className="flex min-w-0 flex-1 flex-col gap-2 pb-4">
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
        {reviewing && checkpoint && (
          <FlowReviewActions flowId={flowId} runId={run.id} checkpoint={checkpoint} />
        )}
        {hasInput && (
          <Collapsible trigger={t("flow_step_show_input")} defaultIsOpen={false}>
            <div className="pt-1">
              <Payload payload={step.input_payload_json} />
            </div>
          </Collapsible>
        )}
        {hasOutput && (
          <Collapsible trigger={t("flow_step_show_output")} defaultIsOpen>
            <div className="pt-1">
              <Payload payload={step.output_payload_json} />
            </div>
          </Collapsible>
        )}
        {files.length > 0 && <FlowRunFiles files={files} label={t("flow_step_files_label")} />}
      </div>
    </li>
  );
}

function RunInputs({ run, definition }: { run: FlowRunPublic; definition: FlowDefinition | null }) {
  const t = useTranslations();
  const values = Object.entries(run.input_payload_json ?? {}).filter(
    ([, value]) => value != null && value !== ""
  );
  const files = run.input_files ?? [];
  if (values.length === 0 && files.length === 0) return null;
  const labelOf = (key: string) =>
    definition?.form_fields.find((field) => field.key === key)?.label ?? key;
  return (
    <Field label={t("flow_run_inputs")}>
      <div className="flex flex-col gap-1.5">
        {values.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {values.map(([key, value]) => (
              <Chip key={key}>
                {labelOf(key)}: {typeof value === "string" ? value : JSON.stringify(value)}
              </Chip>
            ))}
          </div>
        )}
        <FlowRunFiles files={files} label={t("flow_run_input_files")} />
      </div>
    </Field>
  );
}

/**
 * One run: its status and timing, what it was started with, every step with
 * its input and output (text as Markdown, JSON as it is, files as chips that
 * open in the panel), the error if it failed, the review decision while it
 * waits, and a cancel while it can still be stopped. Polled while active.
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
      <Button label={t("flow_runs_back")} variant="ghost" size="sm" onClick={onBack} />
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
                  {t("flow_run_version", { version: data.flow_version })}
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
            {data.error && (
              <p
                role="alert"
                className="bg-ax-error-muted text-ax-error rounded-ax-inner m-0 px-3 py-2 text-[13px]"
              >
                {data.error.code ? `${data.error.code}: ` : ""}
                {data.error.message}
              </p>
            )}
            <dl className="m-0 flex flex-col gap-3">
              <RunInputs run={data} definition={definition} />
              {(data.result_files?.length ?? 0) > 0 && (
                <Field label={t("flow_run_results")}>
                  <FlowRunFiles files={data.result_files!} label={t("flow_run_results")} />
                </Field>
              )}
            </dl>
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
