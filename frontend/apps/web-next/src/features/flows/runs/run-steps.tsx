"use client";

import { Collapsible } from "@astryxdesign/core/Collapsible";
import { useLocale, useTranslations } from "next-intl";
import { QuietBanner } from "@/components/astryx/banner";
import { StatusLabel } from "@/components/composites/status-label";
import { formatCount, formatSeconds, stepInputFiles } from "./run-format";
import { JsonValue } from "./run-json";
import { flowErrorText, runErrorText } from "./run-messages";
import { outputStructured, outputText, tokenTotal, type RunStepView } from "./run-progress";
import { RunFiles, RunInputFiles } from "./run-files";
import { stepStatusView } from "./run-status";
import type { RunStep } from "./runs-api";

type Translate = ReturnType<typeof useTranslations>;

export function stepTitle(step: Pick<RunStepView, "order" | "label">, t: Translate): string {
  return step.label.trim()
    ? t("flow_runs_step_title", { order: step.order, label: step.label.trim() })
    : t("flow_runs_step_title_unnamed", { order: step.order });
}

function stepDurationMs(result: RunStep): number | null {
  if (!result.started_at || !result.finished_at) return null;
  const ms = Date.parse(result.finished_at) - Date.parse(result.started_at);
  return Number.isFinite(ms) && ms >= 0 ? ms : null;
}

/** What a step produced: its text, its structured value, or both when they differ in kind. */
function StepOutput({ result }: { result: RunStep }) {
  const t = useTranslations();
  const payload = result.output_payload_json;
  const structured = outputStructured(payload);
  const text = outputText(payload);
  if (structured !== undefined) return <JsonValue value={structured} />;
  if (text !== null) {
    return (
      <div className="flex flex-col gap-1">
        <p className="text-ax-text text-sm break-words whitespace-pre-wrap">{text}</p>
        {payload?.text_overflow ? (
          <p className="text-ax-text-secondary text-xs">{t("flow_runs_output_overflow")}</p>
        ) : null}
      </div>
    );
  }
  return <p className="text-ax-text-secondary text-sm">{t("flow_runs_output_none")}</p>;
}

/** What the step's answer leaned on: the cited sources, as the core resolved them. */
function StepCitations({ result }: { result: RunStep }) {
  const t = useTranslations();
  const summary = result.citation_summary;
  if (!summary || summary.status === "unavailable") return null;
  const names = summary.sources
    .map((source) =>
      [source.display_name ?? t("flow_runs_citation_unnamed"), source.container_label]
        .filter(Boolean)
        .join(" · ")
    )
    .filter(Boolean);
  return (
    <div className="flex flex-col gap-1">
      <p className="text-ax-text text-sm font-medium">{t("flow_runs_citations_heading")}</p>
      {summary.status === "missing_required_citations" ? (
        <p className="text-ax-text text-sm">{t("flow_runs_citations_missing")}</p>
      ) : summary.status === "unknown_citation_ids_present" ? (
        <p className="text-ax-text text-sm">{t("flow_runs_citations_unknown")}</p>
      ) : summary.status === "citations_on_without_sources" ? (
        <p className="text-ax-text text-sm">{t("flow_runs_citations_no_sources")}</p>
      ) : null}
      {names.length > 0 ? (
        <ul className="text-ax-text flex list-disc flex-col gap-0.5 pl-5 text-sm">
          {names.map((name, index) => (
            <li key={index}>{name}</li>
          ))}
        </ul>
      ) : null}
      {summary.sources_truncated ? (
        <p className="text-ax-text-secondary text-xs">{t("flow_runs_citations_truncated")}</p>
      ) : null}
      {summary.stale_after_edit ? (
        <p className="text-ax-text-secondary text-xs">{t("flow_runs_citations_stale")}</p>
      ) : null}
    </div>
  );
}

function StepCard({ flowId, runId, step }: { flowId: string; runId: string; step: RunStepView }) {
  const t = useTranslations();
  const locale = useLocale();
  const view = stepStatusView(step.status);
  const result = step.result;
  const duration = result ? stepDurationMs(result) : null;
  const tokens = result ? tokenTotal(result.num_tokens_input, result.num_tokens_output) : null;
  const title = stepTitle(step, t);
  const warnings = (result?.diagnostics ?? []).filter((item) => item.severity !== "info");

  return (
    <article
      aria-label={title}
      className="border-ax-border rounded-ax-element flex flex-col gap-3 border p-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="text-ax-text text-base font-semibold break-words">{title}</h3>
        <StatusLabel status={view.tone} label={t(view.labelKey)} isPulsing={view.isPulsing} />
      </div>
      {duration !== null || tokens !== null ? (
        <p className="text-ax-text-secondary text-sm">
          {[
            duration !== null
              ? t("flow_runs_step_took", { time: formatSeconds(duration / 1000, t) })
              : null,
            tokens !== null ? t("flow_runs_tokens", { count: formatCount(tokens, locale) }) : null
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      ) : null}
      {result?.status === "failed" ? (
        <QuietBanner
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
      {warnings.length > 0 ? (
        <ul className="text-ax-text flex list-disc flex-col gap-0.5 pl-5 text-sm">
          {warnings.map((item, index) => (
            <li key={`${item.code}-${index}`}>{flowErrorText(item.code, t) ?? item.message}</li>
          ))}
        </ul>
      ) : null}
      {result && result.status === "completed" ? (
        <div className="flex flex-col gap-2">
          <StepOutput result={result} />
          <RunFiles
            flowId={flowId}
            runId={runId}
            files={result.result_files ?? []}
            label={t("flow_runs_step_files", { step: title })}
          />
          <StepCitations result={result} />
        </div>
      ) : null}
      {result && (result.runtime_input_file_ids ?? []).length > 0 ? (
        <div className="flex flex-col gap-1">
          <p className="text-ax-text text-sm font-medium">{t("flow_runs_step_input_files")}</p>
          <RunInputFiles
            flowId={flowId}
            runId={runId}
            files={stepInputFiles(result)}
            label={t("flow_runs_step_input_files")}
          />
        </div>
      ) : null}
      {result?.input_payload_json && Object.keys(result.input_payload_json).length > 0 ? (
        <Collapsible
          defaultIsOpen={false}
          chevronPosition="start"
          trigger={<span className="text-sm font-medium">{t("flow_runs_step_input")}</span>}
        >
          <div className="pt-2">
            <JsonValue value={result.input_payload_json} />
          </div>
        </Collapsible>
      ) : null}
    </article>
  );
}

/**
 * The run's steps in order, each with its status, how long it took and what
 * it used, what it produced (text, a structured value, files), the sources
 * it cited, and why it failed when it did.
 */
export function RunSteps({
  flowId,
  runId,
  steps
}: {
  flowId: string;
  runId: string;
  steps: readonly RunStepView[];
}) {
  const t = useTranslations();
  if (steps.length === 0) {
    return <p className="text-ax-text-secondary text-sm">{t("flow_runs_steps_none")}</p>;
  }
  return (
    <ol className="m-0 flex flex-col gap-3 p-0">
      {steps.map((step) => (
        <li key={step.order} className="list-none">
          <StepCard flowId={flowId} runId={runId} step={step} />
        </li>
      ))}
    </ol>
  );
}
