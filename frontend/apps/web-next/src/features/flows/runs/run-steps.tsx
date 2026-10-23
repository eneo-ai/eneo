"use client";

import { Collapsible } from "@astryxdesign/core/Collapsible";
import { Token } from "@astryxdesign/core/Token";
import { useLocale, useTranslations } from "next-intl";
import { Banner } from "@astryxdesign/core/Banner";
import { StatusLabel } from "@/components/composites/status-label";
import { LongMaterialCoverage } from "../long-material-coverage";
import { CitationSummary } from "./run-citations";
import { CopyButton } from "./run-copy";
import { formatCount, formatSeconds, stepInputFiles } from "./run-format";
import { JsonValue } from "./run-json";
import { flowErrorText, runErrorText } from "./run-messages";
import {
  nextStepOrder,
  outputStructured,
  outputText,
  stepNeverRan,
  tokenTotal,
  type RunStepView
} from "./run-progress";
import { RunFiles, RunInputFiles } from "./run-files";
import { NOT_RUN_STEP_VIEW, stepStatusView } from "./run-status";
import { StepAttempts } from "./run-step-attempts";
import { StepPromptDetails } from "./run-step-details";
import {
  StepRejectedOutput,
  StepRuntimeInputSummary,
  StepSectionReading,
  StepTemplateProvenance,
  StepTranscriptionFacts
} from "./run-step-extras";
import { runtimeInputSummary, speakerMapping } from "./run-step-facts";
import { StepSpeakerMapping } from "./run-step-speakers";
import { RunText } from "./run-text";
import type { RunStep } from "./runs-api";

type Translate = ReturnType<typeof useTranslations>;

export function stepTitle(step: Pick<RunStepView, "order" | "label">, t: Translate): string {
  return step.label.trim()
    ? t("flow_runs_step_title", { order: step.order, label: step.label.trim() })
    : t("flow_runs_step_title_unnamed", { order: step.order });
}

/** The id of a step's card on the run page, to go to it. */
export function runStepAnchorId(order: number): string {
  return `flow-run-step-${order}`;
}

/** Brings a step's card into view and moves focus to it. */
export function showRunStep(order: number): void {
  const card = document.getElementById(runStepAnchorId(order));
  if (!card) return;
  const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
  card.scrollIntoView?.({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
  card.focus({ preventScroll: true });
}

function stepDurationMs(result: RunStep): number | null {
  if (!result.started_at || !result.finished_at) return null;
  const ms = Date.parse(result.finished_at) - Date.parse(result.started_at);
  return Number.isFinite(ms) && ms >= 0 ? ms : null;
}

/**
 * What a step produced, with a button that copies it: the speakers a
 * speaker-mapping step named, a structured value (marked as JSON), or text
 * (rendered as Markdown, its line breaks kept).
 */
function StepOutput({ flowId, runId, result }: { flowId: string; runId: string; result: RunStep }) {
  const t = useTranslations();
  const payload = result.output_payload_json;
  const structured = outputStructured(payload);
  const text = outputText(payload);
  if (structured === undefined && text === null) {
    return <p className="text-ax-text-secondary text-sm">{t("flow_runs_output_none")}</p>;
  }
  return (
    <div className="flex items-start gap-2">
      <div className="min-w-0 flex-1">
        {speakerMapping(payload) ? (
          <StepSpeakerMapping flowId={flowId} runId={runId} payload={payload} />
        ) : structured !== undefined ? (
          <div className="flex flex-col items-start gap-1">
            <Token size="sm" label={t("flow_run_more_json")} />
            <JsonValue value={structured} />
          </div>
        ) : (
          <div className="flex flex-col gap-1">
            <RunText text={text ?? ""} />
            {payload?.text_overflow ? (
              <p className="text-ax-text-secondary text-xs">{t("flow_runs_output_overflow")}</p>
            ) : null}
          </div>
        )}
      </div>
      <CopyButton label={t("flow_run_more_copy_output")} value={structured ?? text} />
    </div>
  );
}

function StepCard({
  flowId,
  runId,
  step,
  isNext,
  notRun,
  canReadEvidence
}: {
  flowId: string;
  runId: string;
  step: RunStepView;
  isNext: boolean;
  /** The run ended without the step starting. */
  notRun: boolean;
  canReadEvidence: boolean;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const view = notRun ? NOT_RUN_STEP_VIEW : stepStatusView(step.status);
  const result = step.result;
  const duration = result ? stepDurationMs(result) : null;
  const tokens = result ? tokenTotal(result.num_tokens_input, result.num_tokens_output) : null;
  // A step that ran and ended without counts: its usage was not recorded, not zero.
  const usageNotRecorded =
    !notRun &&
    tokens === null &&
    (result?.status === "completed" || result?.status === "failed") &&
    Boolean(result.started_at);
  const title = stepTitle(step, t);
  const warnings = (result?.diagnostics ?? []).filter((item) => item.severity !== "info");

  return (
    <article
      id={runStepAnchorId(step.order)}
      tabIndex={-1}
      aria-label={title}
      className="border-ax-border rounded-ax-element focus-visible:outline-ring flex scroll-mt-4 flex-col gap-3 border p-4 focus-visible:outline-2 focus-visible:outline-offset-2"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="text-ax-text text-base font-semibold break-words">{title}</h3>
        <StatusLabel status={view.tone} label={t(view.labelKey)} isPulsing={view.isPulsing} />
      </div>
      {isNext ? (
        <p className="text-ax-text-secondary text-sm">{t("flow_run_progress_next_step_hint")}</p>
      ) : null}
      {step.status === "running" ? (
        <p className="text-ax-text-secondary text-sm">
          {step.speakerIdentification
            ? t("flow_run_progress_transcribing_with_speakers_hint")
            : t("flow_run_progress_running_body")}
        </p>
      ) : null}
      {duration !== null || tokens !== null || usageNotRecorded ? (
        <p className="text-ax-text-secondary text-sm">
          {[
            duration !== null
              ? t("flow_runs_step_took", { time: formatSeconds(duration / 1000, t) })
              : null,
            tokens !== null && result
              ? t("flow_run_journey_step_tokens", {
                  total: formatCount(tokens, locale),
                  input: formatCount(result.num_tokens_input ?? 0, locale),
                  output: formatCount(result.num_tokens_output ?? 0, locale)
                })
              : usageNotRecorded
                ? t("flow_run_token_usage_not_recorded")
                : null
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      ) : null}
      {result?.status === "failed" && !notRun ? (
        <Banner
          status="error"
          title={t("flow_runs_step_failed_title")}
          description={
            result.error_code
              ? runErrorText({ code: result.error_code, details: null }, t)
              : t("flow_runs_error_unknown")
          }
          collapsible={false}
        />
      ) : null}
      {result?.status === "failed" && !notRun ? (
        <StepRejectedOutput payload={result.output_payload_json} />
      ) : null}
      {warnings.length > 0 ? (
        <ul className="text-ax-text flex list-disc flex-col gap-0.5 pl-5 text-sm">
          {warnings.map((item, index) => (
            <li key={`${item.code}-${index}`}>{flowErrorText(item.code, t) ?? item.message}</li>
          ))}
        </ul>
      ) : null}
      {result?.long_material ? <LongMaterialCoverage coverage={result.long_material} /> : null}
      {result && result.status === "completed" ? (
        <div className="flex flex-col gap-2">
          <StepOutput flowId={flowId} runId={runId} result={result} />
          <StepSectionReading payload={result.output_payload_json} />
          <StepTemplateProvenance payload={result.output_payload_json} />
          <RunFiles
            flowId={flowId}
            runId={runId}
            files={result.result_files ?? []}
            label={t("flow_runs_step_files", { step: title })}
          />
          <CitationSummary summary={result.citation_summary} />
        </div>
      ) : null}
      {result &&
      ((result.runtime_input_file_ids ?? []).length > 0 || runtimeInputSummary(result)) ? (
        <div className="flex flex-col gap-1">
          <p className="text-ax-text text-sm font-medium">{t("flow_runs_step_input_files")}</p>
          <StepRuntimeInputSummary result={result} />
          <RunInputFiles
            flowId={flowId}
            runId={runId}
            files={stepInputFiles(result)}
            label={t("flow_runs_step_input_files")}
          />
        </div>
      ) : null}
      {result ? <StepTranscriptionFacts result={result} /> : null}
      {result?.input_payload_json && Object.keys(result.input_payload_json).length > 0 ? (
        <Collapsible
          defaultIsOpen={false}
          chevronPosition="start"
          trigger={<span className="text-sm font-medium">{t("flow_runs_step_input")}</span>}
        >
          <div className="flex items-start gap-2 pt-2">
            <div className="min-w-0 flex-1">
              <JsonValue value={result.input_payload_json} />
            </div>
            <CopyButton label={t("flow_run_more_copy_input")} value={result.input_payload_json} />
          </div>
        </Collapsible>
      ) : null}
      {result ? <StepPromptDetails result={result} /> : null}
      {canReadEvidence && result?.started_at ? (
        <StepAttempts flowId={flowId} runId={runId} order={step.order} title={title} />
      ) : null}
    </article>
  );
}

/**
 * The run's steps in order, each with its status, how long it took and the
 * tokens it used in and out (or that its usage was not recorded), what it produced (text, a structured value,
 * the speakers it named, files; how it read long material and the document
 * template it filled), the sources it cited, what was sent in at run time,
 * how it transcribed audio, and why it failed when it did, with the answer
 * it gave that was not accepted. A step of an ended run that never started
 * reads "did not run". A running step says what it is doing and the step
 * next in turn says so. A caller who may read the evidence can open each
 * step's attempts. Each card can be gone to (`showRunStep`), as the failure
 * notice does.
 */
export function RunSteps({
  flowId,
  runId,
  steps,
  runStatus = null,
  canReadEvidence = false
}: {
  flowId: string;
  runId: string;
  steps: readonly RunStepView[];
  /** The run's status, to tell a step that never ran from one that failed. */
  runStatus?: string | null;
  /** The core would let the caller read the run's evidence (its attempts). */
  canReadEvidence?: boolean;
}) {
  const t = useTranslations();
  if (steps.length === 0) {
    return <p className="text-ax-text-secondary text-sm">{t("flow_runs_steps_none")}</p>;
  }
  const next = nextStepOrder(steps);
  return (
    <ol className="m-0 flex flex-col gap-3 p-0">
      {steps.map((step) => (
        <li key={step.order} className="list-none">
          <StepCard
            flowId={flowId}
            runId={runId}
            step={step}
            isNext={step.order === next}
            notRun={stepNeverRan(step, runStatus)}
            canReadEvidence={canReadEvidence}
          />
        </li>
      ))}
    </ol>
  );
}
