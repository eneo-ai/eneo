import type { FlowStep } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";
import { getLocale } from "$lib/paraglide/runtime";
import { parseFlowInputBindings } from "./flowInputBindings";
import { buildContext } from "./components/flowPromptVariables";
import { getRuntimeInputConfig } from "./flowRuntimeInputConfig";
import {
  findToolOption,
  readToolInputConfig,
  type FlowToolOption
} from "./components/tool/toolInputConfig";
import {
  classifyVariable,
  extractTemplateTokens,
  isValidStepInputPath,
  readsFlowInputToken,
  referencedStepOrder,
  type VariableClassificationContext
} from "./flowVariableTokens";

/**
 * What the AI reads in a step, in the runtime's order
 * (step_input_resolution.resolve_step_input_binding): the step's own text,
 * then the results chosen from earlier steps, then the step's source. One
 * owner so the material block, the step list, the chapter summary and the
 * request preview say the same thing.
 */
export type StepMaterial =
  | { kind: "own_text"; withUpload: boolean; withSources: boolean }
  | { kind: "sources" }
  | { kind: "upload" }
  | { kind: "previous_step"; stepOrder: number; stepName: string | null }
  | { kind: "all_previous_steps" }
  | { kind: "web_address" }
  | { kind: "tool" }
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
  if (step.input_source === "tool") return { kind: "tool" };
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
    case "tool":
      return m.flow_material_what_tool();
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
};

function listed(parts: string[]): string {
  return new Intl.ListFormat(getLocale(), { type: "conjunction" }).format(parts);
}

function sourceLine(parts: string[], readsRunInput = false): StepSourceLine {
  return { text: m.flow_step_reads({ what: listed(parts) }), readsRunInput };
}

/** Earlier steps by number: up to three are named ("steg 1 och 2"), more are counted. */
function stepParts(orders: number[], alone: boolean): string[] {
  if (orders.length > 3) return [m.flow_step_reads_steps({ count: orders.length })];
  if (alone && orders.length > 1) {
    return [m.flow_step_reads_steps_numbered({ steps: listed(orders.map(String)) })];
  }
  return orders.map((order) => m.flow_step_reads_step({ step: order }));
}

/** `tools` is the editor's list of the flow's tools, which names a step's chosen tool. */
export function getStepSourceLine(
  step: MaterialStep,
  previousStep: PreviousStep,
  context: VariableClassificationContext,
  tools: readonly FlowToolOption[] = []
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
      const flowInput = tokens.some((token) => readsFlowInputToken(token, context));
      // Every way to read an earlier step, through one resolver: chosen results
      // and text references alike may name a step by number or by name, and
      // the text may use the previous-step alias. Later or missing steps read nothing.
      const references = [
        ...(bindings.status === "valid" ? bindings.sourceRefs.map((ref) => ref.stepRef) : []),
        ...tokens
      ];
      const orders = [
        ...new Set(references.flatMap((reference) => referencedStepOrder(reference, context) ?? []))
      ].sort((a, b) => a - b);
      const inputs = [
        ...(upload ? [m.flow_step_reads_upload()] : []),
        ...(form ? [m.flow_step_reads_form()] : []),
        ...(flowInput ? [m.flow_step_reads_flow_input()] : [])
      ];
      const parts = [...inputs, ...stepParts(orders, inputs.length === 0)];
      if (parts.length === 0) return { text: m.flow_step_reads_own_text(), readsRunInput: false };
      return sourceLine(parts, inputs.length > 0);
    }
    case "upload":
      return sourceLine([m.flow_step_reads_upload()], true);
    case "flow_input":
      return sourceLine([m.flow_step_reads_flow_input()], true);
    case "previous_step":
      // The usual source, said relatively: a chain of such steps shares one caption.
      return sourceLine([m.flow_step_reads_previous()]);
    case "all_previous_steps":
      return sourceLine([m.flow_step_reads_all_previous()]);
    case "web_address":
      return sourceLine([m.flow_step_reads_web()]);
    case "tool": {
      const tool = findToolOption(tools, readToolInputConfig(step.input_config));
      return sourceLine([
        tool
          ? m.flow_step_reads_tool_named({ tool: tool.tool_name, server: tool.mcp_server_name })
          : m.flow_step_reads_tool()
      ]);
    }
  }
}

/**
 * Every step's source line, in the words the step panel uses: the step list's
 * captions read this line. A template step
 * names its template instead, so it has none.
 */
export function stepSourceLines(
  steps: FlowStep[],
  formSchema: Parameters<typeof buildContext>[1],
  transcriptionEnabled: boolean,
  tools: readonly FlowToolOption[] = []
): (StepSourceLine | null)[] {
  return steps.map((step) =>
    step.output_mode === "template_fill"
      ? null
      : getStepSourceLine(
          step,
          steps.find((candidate) => candidate.step_order === step.step_order - 1),
          buildContext(steps, formSchema, transcriptionEnabled, step.step_order),
          tools
        )
  );
}

/**
 * Steps in a row that read the same thing share one caption, so the step list
 * says it once ("Läser steg 1" over twenty steps) and every step sits under a
 * caption that is true for it. For each step: the index of the step whose line
 * captions it, or null when it has no line.
 */
export function groupStepSources(lines: readonly (StepSourceLine | null)[]): (number | null)[] {
  const captionOf: (number | null)[] = [];
  for (const [index, line] of lines.entries()) {
    const continues = index > 0 && line !== null && lines[index - 1]?.text === line.text;
    captionOf.push(line === null ? null : continues ? (captionOf[index - 1] ?? index) : index);
  }
  return captionOf;
}
