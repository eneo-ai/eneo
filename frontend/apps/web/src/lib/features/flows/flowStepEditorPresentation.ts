import type { FlowStep } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";

/**
 * What the middle of a step's flow capsule describes — the "AI work" segment
 * that sits between the input and output. Derived from the step alone so the
 * capsule, status, and any next-action all read from one source and cannot
 * contradict each other.
 */
export type StepAiWorkKind =
  "transcribe" | "http" | "template" | "document" | "missing" | "process";

export function getStepAiWorkKind(
  step: FlowStep,
  { instructionPresent }: { instructionPresent: boolean | null }
): StepAiWorkKind {
  if (step.output_mode === "transcribe_only") return "transcribe";
  if (
    step.output_mode === "http_post" ||
    step.input_source === "http_get" ||
    step.input_source === "http_post"
  ) {
    return "http";
  }
  if (step.output_mode === "template_fill") return "template";
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

export function getStepAiWork(
  step: FlowStep,
  opts: { instructionPresent: boolean | null }
): StepAiWork {
  const kind = getStepAiWorkKind(step, opts);
  const text =
    kind === "transcribe"
      ? m.flow_capsule_ai_transcribe()
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
