import type { FlowStep } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";
import { parseFlowInputBindings } from "./flowInputBindings";
import { getRuntimeInputConfig } from "./flowRuntimeInputConfig";
import {
  collectTemplateStepReferenceOrders,
  extractTemplateTokens,
  isValidStepInputPath
} from "./flowVariableTokens";

/**
 * What the AI reads in a step, in the runtime's order
 * (step_input_resolution.resolve_step_input_binding): the step's own text,
 * then the results chosen from earlier steps, then the step's source. One
 * owner so the material block, the chapter summary and the request preview
 * say the same thing.
 */
export type StepMaterial =
  | { kind: "own_text"; withUpload: boolean; withSources: boolean; stepOrders: number[] }
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
      withSources: bindings.status === "valid" && bindings.sourceRefs.length > 0,
      stepOrders: collectTemplateStepReferenceOrders(ownText)
    };
  }
  return getDefaultStepMaterial(step, previousStep);
}

function stepLabel(stepOrder: number, stepName: string | null): string {
  const base = m.flow_input_template_effective_step({ step: stepOrder });
  return stepName ? `${base}: ${stepName}` : base;
}

/**
 * The material as a phrase that completes "AI:n läser …". `below` is for the
 * block that shows the own text right under the sentence.
 */
export function describeStepMaterial(material: StepMaterial, { below = false } = {}): string {
  switch (material.kind) {
    case "own_text":
      if (material.withSources) {
        return below
          ? m.flow_material_what_own_text_and_sources()
          : m.flow_material_what_own_text_and_sources_short();
      }
      if (material.withUpload) {
        return below
          ? m.flow_material_what_own_text_with_upload()
          : m.flow_material_what_own_text_with_upload_short();
      }
      return below ? m.flow_material_what_own_text() : m.flow_material_what_own_text_short();
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
 * The same phrase with its first letter raised, for a summary line of its
 * own. A summary also names the earlier steps an own text reads.
 */
export function describeStepMaterialAsSummary(material: StepMaterial): string {
  const phrase =
    material.kind === "own_text" && material.stepOrders.length > 0 && !material.withSources
      ? m.flow_material_what_own_text_with_steps_short({
          steps: material.stepOrders
            .map((order) => m.flow_input_template_effective_step({ step: order }))
            .join(", ")
        })
      : describeStepMaterial(material);
  return phrase.charAt(0).toLocaleUpperCase() + phrase.slice(1);
}
