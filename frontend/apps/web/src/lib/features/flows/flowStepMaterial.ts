import type { FlowStep } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";
import { getLocale } from "$lib/paraglide/runtime";
import { FLOW_INPUT_ALIASES } from "./flowFormSchema";
import { getFlowStepUnderlag, parseFlowInputBindings } from "./flowInputBindings";
import { getRuntimeInputConfig } from "./flowRuntimeInputConfig";
import {
  classifyVariable,
  extractTemplateTokens,
  isValidStepInputPath,
  type VariableClassificationContext
} from "./flowVariableTokens";

/**
 * What the AI reads in a step, in the runtime's order
 * (step_input_resolution.resolve_step_input_binding): the step's own text,
 * then the results chosen from earlier steps, then the step's source. One
 * owner so the material block, the chapter summary and the request preview
 * say the same thing.
 */
export type StepMaterial =
  | { kind: "own_text"; withUpload: boolean; withSources: boolean }
  | { kind: "sources" }
  | { kind: "upload" }
  | { kind: "previous_step"; stepOrder: number; stepName: string | null }
  | { kind: "all_previous_steps" }
  | { kind: "web_address" }
  | { kind: "flow_input" };

type MaterialStep = Pick<FlowStep, "step_order" | "input_source" | "input_bindings"> &
  Partial<Pick<FlowStep, "input_config" | "input_type" | "output_mode">>;

function receivesUpload(step: MaterialStep): boolean {
  return getRuntimeInputConfig({ ...step, input_config: step.input_config ?? null }).enabled;
}

type PreviousStep = Pick<FlowStep, "step_order" | "user_description"> | null | undefined;

/**
 * True when the text reads the upload through a reference the runtime
 * accepts (`consumes_runtime_input`): a whole token with a valid
 * `step_input` path. A typo or an unclosed token does not count.
 */
export function ownTextIncludesUpload(text: string): boolean {
  return extractTemplateTokens(text).some(
    (token) =>
      token.startsWith("step_input.") && isValidStepInputPath(token.slice("step_input.".length))
  );
}

/** What the step reads when it has no text of its own; null when the source is unknown. */
export function getDefaultStepMaterial(
  step: MaterialStep,
  previousStep: PreviousStep
): StepMaterial | null {
  const bindings = parseFlowInputBindings(step.input_bindings);
  if (bindings.status === "valid" && bindings.sourceRefs.length > 0) return { kind: "sources" };
  if (receivesUpload(step)) return { kind: "upload" };
  if (step.input_source === "previous_step" && step.step_order > 1 && previousStep) {
    return {
      kind: "previous_step",
      stepOrder: previousStep.step_order,
      stepName: previousStep.user_description?.trim() || null
    };
  }
  if (step.input_source === "all_previous_steps" && step.step_order > 1) {
    return { kind: "all_previous_steps" };
  }
  if (step.input_source === "http_get") return { kind: "web_address" };
  if (step.input_source === "flow_input") return { kind: "flow_input" };
  return null;
}

/** What the step reads now: its own text when it has one, otherwise its usual material. */
export function getStepMaterial(
  step: MaterialStep,
  previousStep: PreviousStep
): StepMaterial | null {
  const bindings = parseFlowInputBindings(step.input_bindings);
  const ownText = bindings.status === "valid" ? (bindings.question ?? "").trim() : "";
  if (ownText) {
    return {
      kind: "own_text",
      withUpload: receivesUpload(step) && ownTextIncludesUpload(ownText),
      withSources: bindings.status === "valid" && bindings.sourceRefs.length > 0
    };
  }
  return getDefaultStepMaterial(step, previousStep);
}

function stepLabel(stepOrder: number, stepName: string | null): string {
  const base = m.flow_input_template_effective_step({ step: stepOrder });
  return stepName ? `${base}: ${stepName}` : base;
}

/**
 * The material as a phrase that completes "AI:n läser …". An own text is
 * always shown right under the sentence, so its phrase says so.
 */
export function describeStepMaterial(material: StepMaterial): string {
  switch (material.kind) {
    case "own_text":
      if (material.withSources) return m.flow_material_what_own_text_and_sources();
      if (material.withUpload) return m.flow_material_what_own_text_with_upload();
      return m.flow_material_what_own_text();
    case "sources":
      return m.flow_material_what_sources();
    case "upload":
      return m.flow_material_what_upload();
    case "previous_step":
      return m.flow_material_what_previous({
        step: stepLabel(material.stepOrder, material.stepName)
      });
    case "all_previous_steps":
      return m.flow_material_what_all_previous();
    case "web_address":
      return m.flow_material_what_http();
    case "flow_input":
      return m.flow_material_what_flow_input();
  }
}

/**
 * Where a step's material comes from, sources first, for the step list and
 * the Underlag chapter ("Läser det uppladdade underlaget och formuläret").
 */
export type StepSourceLine = {
  text: string;
  /** Takes in what the flow is given when it runs (the upload, the form, its input). */
  readsRunInput: boolean;
  /** Reads only the step right before it: the usual case the step list keeps quiet. */
  readsOnlyPreviousStep: boolean;
};

/** A reference to the flow's own input: an alias, or a flow input path that is not a form field. */
function readsFlowInput(token: string, context: VariableClassificationContext): boolean {
  if (FLOW_INPUT_ALIASES.has(token)) return true;
  return (
    (token.startsWith("flow_input.") || token.startsWith("flow.input.")) &&
    classifyVariable(token, context) === "technical"
  );
}

function sourceLine(
  parts: string[],
  readsRunInput: boolean,
  readsOnlyPreviousStep = false
): StepSourceLine {
  const what = new Intl.ListFormat(getLocale(), { type: "conjunction" }).format(parts);
  return { text: m.flow_step_reads({ what }), readsRunInput, readsOnlyPreviousStep };
}

export function getStepSourceLine(
  step: MaterialStep,
  previousStep: PreviousStep,
  context: VariableClassificationContext
): StepSourceLine | null {
  const material = getStepMaterial(step, previousStep);
  if (!material) return null;
  switch (material.kind) {
    case "own_text":
    case "sources": {
      const bindings = parseFlowInputBindings(step.input_bindings);
      const tokens = extractTemplateTokens(
        bindings.status === "valid" ? (bindings.question ?? "") : ""
      );
      const upload = material.kind === "own_text" && material.withUpload;
      const form = tokens.some((token) => classifyVariable(token, context) === "field");
      const flowInput = tokens.some((token) => readsFlowInput(token, context));
      const orders = getFlowStepUnderlag(step)?.stepOrders ?? [];
      const parts = [
        ...(upload ? [m.flow_step_reads_upload()] : []),
        ...(form ? [m.flow_step_reads_form()] : []),
        ...(flowInput ? [m.flow_step_reads_flow_input()] : []),
        // Two steps read well by number; more become a count.
        ...(orders.length > 2
          ? [m.flow_step_reads_steps({ count: orders.length })]
          : orders.map((order) => m.flow_step_reads_step({ step: order })))
      ];
      if (parts.length === 0) {
        return {
          text: m.flow_step_reads_own_text(),
          readsRunInput: false,
          readsOnlyPreviousStep: false
        };
      }
      const runInput = upload || form || flowInput;
      return sourceLine(
        parts,
        runInput,
        !runInput && orders.length === 1 && orders[0] === step.step_order - 1
      );
    }
    case "upload":
      return sourceLine([m.flow_step_reads_upload()], true);
    case "flow_input":
      return sourceLine([m.flow_step_reads_flow_input()], true);
    case "previous_step":
      return sourceLine([m.flow_step_reads_step({ step: material.stepOrder })], false, true);
    case "all_previous_steps":
      return sourceLine([m.flow_step_reads_all_previous()], false);
    case "web_address":
      return sourceLine([m.flow_step_reads_web()], false);
  }
}

/**
 * Steps in a row that read the same thing share one caption, so the step list
 * says it once ("Läser steg 1" over twenty steps). A lone step that just reads
 * the one before gets none, as in a plain step-by-step flow. For each step:
 * the index of the step whose line captions it, or null.
 */
export function groupStepSources(lines: readonly (StepSourceLine | null)[]): (number | null)[] {
  const captionOf: (number | null)[] = [];
  let runText: string | null = null;
  let runStart: number | null = null;
  for (const [index, line] of lines.entries()) {
    if (!line) {
      runText = null;
      captionOf.push(null);
      continue;
    }
    if (line.text !== runText) {
      const quiet = line.readsOnlyPreviousStep && lines[index + 1]?.text !== line.text;
      runText = line.text;
      runStart = quiet ? null : index;
    }
    captionOf.push(runStart);
  }
  return captionOf;
}
