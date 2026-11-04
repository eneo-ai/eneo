import { Collapsible } from "@/components/astryx/collapsible";
import { HStack } from "@astryxdesign/core/HStack";
import { ScrollableArea } from "@astryxdesign/core/ScrollableArea";
import { Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";
import { VStack } from "@astryxdesign/core/VStack";
import { useLocale, useTranslations } from "use-intl";
import { useState } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { StatusLabel } from "@/components/composites/status-label";
import { LongMaterialCoverage } from "../long-material-coverage";
import { CitationSummary } from "./run-citations";
import { CopyButton } from "./run-copy";
import { formatCount, formatSeconds, stepInputFiles } from "./run-format";
import { JsonBlock, JsonValue } from "./run-json";
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
import { isTerminal, NOT_RUN_STEP_VIEW, stepStatusView } from "./run-status";
import { StepAttempts } from "./run-step-attempts";
import { StepPromptDetails } from "./run-step-details";
import {
  StepRejectedOutput,
  StepRuntimeInputSummary,
  StepSectionReading,
  StepTemplateProvenance,
  StepTranscriptionFacts
} from "./run-step-extras";
import { runtimeInputSummary, speakerMapping, stepInputRest } from "./run-step-facts";
import { StepSpeakerMapping } from "./run-step-speakers";
import { RunText } from "./run-text";
import { TranscriptSlot } from "./run-transcript";
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
 * What a step produced, expanded on demand beside a copy button: the speakers a
 * speaker-mapping step named, a structured value (marked as JSON), or text
 * (rendered as Markdown, its line breaks kept, in a box that scrolls past a
 * height). A step whose text is its transcript shows the transcript
 * (`transcript`), open until the person folds it, as its own section did, and
 * leaves copying to the transcript's export: the text here has no corrections.
 */
function StepOutput({
  flowId,
  runId,
  result,
  transcript = null
}: {
  flowId: string;
  runId: string;
  result: RunStep;
  transcript?: HTMLElement | null;
}) {
  const t = useTranslations();
  const [toggled, setToggled] = useState<boolean | null>(null);
  // A transcript can arrive after the card: the default follows it.
  const open = toggled ?? transcript !== null;
  const payload = result.output_payload_json;
  const structured = outputStructured(payload);
  const text = outputText(payload);
  if (structured === undefined && text === null) {
    return (
      <Text type="supporting" as="p">
        {t("flow_runs_output_none")}
      </Text>
    );
  }
  return (
    <HStack gap={2} vAlign="start">
      <Collapsible
        className="min-w-0 flex-1"
        isOpen={open}
        onOpenChange={setToggled}
        chevronPosition="start"
        trigger={
          <span className="block py-1.5 text-sm font-medium">{t("flow_runs_step_output")}</span>
        }
      >
        {open ? (
          <VStack gap={1} paddingBlockStart={2}>
            {speakerMapping(payload) ? (
              <StepSpeakerMapping flowId={flowId} runId={runId} payload={payload} />
            ) : structured !== undefined ? (
              <VStack gap={1} hAlign="start">
                <Token size="sm" label={t("flow_run_more_json")} />
                <JsonValue value={structured} />
              </VStack>
            ) : transcript ? (
              <TranscriptSlot host={transcript} />
            ) : (
              <StepOutputText payload={payload} />
            )}
          </VStack>
        ) : null}
      </Collapsible>
      {transcript ? null : (
        // Centred on the trigger's row, which is 4 px taller than the button.
        <span className="pt-0.5">
          <CopyButton label={t("flow_run_more_copy_output")} value={structured ?? text} />
        </span>
      )}
    </HStack>
  );
}

/** A step's text output, and that it is shortened when the core cut it. */
function StepOutputText({ payload }: { payload: RunStep["output_payload_json"] }) {
  const t = useTranslations();
  return (
    <>
      <StepText text={outputText(payload) ?? ""} />
      {payload?.text_overflow ? (
        <Text type="supporting" as="p">
          {t("flow_runs_output_overflow")}
        </Text>
      ) : null}
    </>
  );
}

/**
 * What a transcribing step wrote, where its transcript cannot show: with the
 * copy `StepOutput` leaves to the transcript, since this is the text on screen.
 */
export function StepTextInsteadOfTranscript({
  payload
}: {
  payload: RunStep["output_payload_json"];
}) {
  const t = useTranslations();
  return (
    <HStack gap={2} vAlign="start">
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <StepOutputText payload={payload} />
      </div>
      <CopyButton label={t("flow_run_more_copy_output")} value={outputText(payload)} />
    </HStack>
  );
}

/**
 * A step's text in a soft box that wraps and, past a height, scrolls. `label`
 * names the box for a keyboard or screen reader; it is the step's output
 * unless it says otherwise. `plain` is for what a person wrote: input is shown
 * as it was sent, while a step's output is Markdown.
 */
export function StepText({
  text,
  label,
  plain = false
}: {
  text: string;
  label?: string;
  plain?: boolean;
}) {
  const t = useTranslations();
  return (
    <ScrollableArea
      axis="block"
      label={label ?? t("flow_runs_step_output")}
      className="bg-ax-sunken rounded-ax-inner focus-visible:outline-ring max-h-96 min-w-0 px-3 py-2 [overflow-wrap:anywhere] focus-visible:outline-2 focus-visible:-outline-offset-2"
    >
      {plain ? (
        <p className="text-ax-text m-0 text-sm leading-relaxed break-words whitespace-pre-wrap">
          {text}
        </p>
      ) : (
        <RunText text={text} />
      )}
    </ScrollableArea>
  );
}

/** Keys of a step's input that say how its text got there, not what it says. */
const INPUT_ORIGIN = new Set(["input_source", "used_question_binding"]);

/**
 * The text of an input that is nothing but a text: `text` and `source_text`
 * (the core sends the same words in both, or one empty) beside its origin,
 * flags that are off and empty lists. Null when it says anything more.
 */
function inputText({ text, source_text: source, ...rest }: Record<string, unknown>) {
  const words = text || source;
  if (typeof words !== "string" || !words.trim() || (text && source && text !== source)) {
    return null;
  }
  const nothingMore = Object.entries(rest).every(
    ([key, value]) =>
      INPUT_ORIGIN.has(key) || !value || (Array.isArray(value) && value.length === 0)
  );
  return nothingMore ? words : null;
}

/**
 * What a step was sent, less what the card already shows (`stepInputRest`):
 * only a text as that text, anything else as JSON, with a button that copies
 * it, or all of the JSON: closed until asked for, and rendered only while open,
 * since a large input weighs on the page.
 */
function StepInput({ result }: { result: RunStep }) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const rest = stepInputRest(result);
  if (!rest) return null;
  const text = inputText(rest);
  const copyLabel = t("flow_run_more_copy_input");
  return (
    <Collapsible
      className="min-w-0"
      isOpen={open}
      onOpenChange={setOpen}
      chevronPosition="start"
      trigger={
        <span className="block py-1.5 text-sm font-medium">{t("flow_run_step_input_show")}</span>
      }
    >
      {open ? (
        <div className="pt-2">
          {text !== null ? (
            <HStack gap={2} vAlign="start">
              <div className="min-w-0 flex-1">
                <StepText text={text} label={t("flow_runs_input_heading")} plain />
              </div>
              <CopyButton label={copyLabel} value={text} />
            </HStack>
          ) : (
            <JsonBlock value={rest} copy={{ label: copyLabel, value: result.input_payload_json }} />
          )}
        </div>
      ) : null}
    </Collapsible>
  );
}

/** The transcript of a step whose result is something else, open from the start. */
function StepTranscriptSection({ host }: { host: HTMLElement }) {
  const t = useTranslations();
  const [open, setOpen] = useState(true);
  return (
    <Collapsible
      className="min-w-0"
      isOpen={open}
      onOpenChange={setOpen}
      chevronPosition="start"
      trigger={
        <span className="block py-1.5 text-sm font-medium">
          {t("flow_runs_transcript_heading")}
        </span>
      }
    >
      {open ? (
        <div className="pt-2">
          <TranscriptSlot host={host} />
        </div>
      ) : null}
    </Collapsible>
  );
}

function StepCard({
  flowId,
  runId,
  step,
  isNext,
  notRun,
  canReadEvidence,
  runSettled,
  transcript
}: {
  flowId: string;
  runId: string;
  step: RunStepView;
  isNext: boolean;
  /** The run ended without the step starting. */
  notRun: boolean;
  canReadEvidence: boolean;
  /** The run has ended (`isTerminal`). */
  runSettled: boolean;
  /** The element the step's transcript renders into, when it has one to show. */
  transcript: HTMLElement | null;
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
  // A transcribing step's text is its transcript: shown as its result. Any
  // other step that transcribed shows its transcript beside its result.
  const transcriptIsResult =
    transcript !== null &&
    Boolean(step.transcribeOnly) &&
    result?.status === "completed" &&
    outputText(result.output_payload_json) !== null;

  return (
    <article
      id={runStepAnchorId(step.order)}
      tabIndex={-1}
      aria-label={title}
      className="border-ax-border rounded-ax-element focus-visible:outline-ring flex min-w-0 scroll-mt-4 flex-col gap-3 border p-4 focus-visible:outline-2 focus-visible:outline-offset-2"
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
          <StepOutput
            flowId={flowId}
            runId={runId}
            result={result}
            transcript={transcriptIsResult ? transcript : null}
          />
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
      {transcript && !transcriptIsResult ? <StepTranscriptSection host={transcript} /> : null}
      {result ? <StepTranscriptionFacts result={result} /> : null}
      {result ? <StepInput result={result} /> : null}
      {result ? <StepPromptDetails result={result} /> : null}
      {canReadEvidence && result?.started_at ? (
        <StepAttempts
          flowId={flowId}
          runId={runId}
          order={step.order}
          title={title}
          runSettled={runSettled}
        />
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
 * next in turn says so. A step that transcribed audio shows its transcript
 * (`transcripts`, rendered by the page). A caller who may read the evidence
 * can open each step's attempts. Each card can be gone to (`showRunStep`), as
 * the failure notice does.
 */
export function RunSteps({
  flowId,
  runId,
  steps,
  runStatus = null,
  canReadEvidence = false,
  transcripts
}: {
  flowId: string;
  runId: string;
  steps: readonly RunStepView[];
  /** The run's status, to tell a step that never ran from one that failed. */
  runStatus?: string | null;
  /** The core would let the caller read the run's evidence (its attempts). */
  canReadEvidence?: boolean;
  /** By step id, the element each step's transcript renders into (`useTranscriptHosts`). */
  transcripts?: ReadonlyMap<string, HTMLElement>;
}) {
  const t = useTranslations();
  if (steps.length === 0) {
    return <p className="text-ax-text-secondary text-sm">{t("flow_runs_steps_none")}</p>;
  }
  const next = nextStepOrder(steps);
  const runSettled = runStatus !== null && isTerminal(runStatus);
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
            runSettled={runSettled}
            transcript={(step.result && transcripts?.get(step.result.step_id)) ?? null}
          />
        </li>
      ))}
    </ol>
  );
}
