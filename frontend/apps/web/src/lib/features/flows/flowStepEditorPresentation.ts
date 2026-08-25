import type { FlowStep } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";
import { outputModeUsesCompletionModel } from "$lib/features/flows/flowStepTypes";

/**
 * What the middle of a step's flow capsule describes — the "AI work" segment
 * that sits between the input and output. Derived from the step alone so the
 * capsule, status, and any next-action all read from one source and cannot
 * contradict each other.
 */
export type StepAiWorkKind =
  "transcribe" | "speakers" | "http" | "template" | "document" | "missing" | "process";

export function getStepAiWorkKind(
  step: FlowStep,
  { instructionPresent }: { instructionPresent: boolean | null }
): StepAiWorkKind {
  if (step.output_mode === "transcribe_only") return "transcribe";
  if (step.output_mode === "speaker_mapping") return "speakers";
  if (step.output_mode === "http_post" || step.input_source === "http_get") {
    return "http";
  }
  if (step.output_mode === "template_fill") return "template";
  if (!outputModeUsesCompletionModel(step.output_mode)) {
    return step.output_type === "docx" || step.output_type === "pdf" ? "document" : "process";
  }
  // Only report a missing instruction when we actually know it is empty —
  // `null` means the assistant is still loading, so stay neutral.
  if (instructionPresent === false) return "missing";
  // A document output reads as "creates a document" rather than generic work.
  if (step.output_type === "docx" || step.output_type === "pdf") return "document";
  return "process";
}

export interface StepAiWork {
  text: string;
  missing: boolean;
}

export type FlowStepChapterId = "task" | "input" | "result" | "control" | "technical";

export function getDefaultOpenStepChapter({
  step,
  hasInputError = false,
  hasOutputError = false
}: {
  step: Pick<FlowStep, "output_mode">;
  hasInputError?: boolean;
  hasOutputError?: boolean;
}): FlowStepChapterId {
  if (hasInputError) return "input";
  if (hasOutputError) return "result";
  if (step.output_mode === "transcribe_only") return "input";
  if (step.output_mode === "template_fill" || step.output_mode === "render_verbatim") {
    return "result";
  }
  return "task";
}

export function getStepAiWork(
  step: FlowStep,
  opts: { instructionPresent: boolean | null }
): StepAiWork {
  const kind = getStepAiWorkKind(step, opts);
  const text =
    kind === "transcribe"
      ? m.flow_capsule_ai_transcribe()
      : kind === "speakers"
        ? m.flow_capsule_ai_speakers()
        : kind === "http"
          ? m.flow_capsule_ai_http()
          : kind === "template"
            ? m.flow_capsule_ai_template()
            : kind === "document"
              ? m.flow_capsule_ai_document()
              : kind === "missing"
                ? m.flow_capsule_ai_missing()
                : m.flow_capsule_ai_process();
  return { text, missing: kind === "missing" };
}
