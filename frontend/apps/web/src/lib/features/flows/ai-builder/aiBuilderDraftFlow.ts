import type { Flow, FlowStep } from "@intric/intric-js";
import type { FlowDraftSpecCore, StepSpec } from "./protocol";

/**
 * Map a draft plan's steps onto the editor's FlowStep shape so the AI builder can
 * render the proposed flow with the existing FlowGraph. Optional shape fields fall
 * back to the same defaults the backend spec applies.
 */
export function planStepsToFlowSteps(steps: StepSpec[]): FlowStep[] {
  return steps.map((step, index) => ({
    id: step.plan_step_ref,
    // A draft step has no real assistant yet. FlowGraph only fetches assistant
    // metadata for non-empty ids, so an empty id keeps the canvas a pure local
    // render with no network calls.
    assistant_id: "",
    step_order: index + 1,
    user_description: step.name,
    input_source: step.input_source,
    input_type: step.input_type ?? "text",
    output_mode: step.output_mode ?? "pass_through",
    output_type: step.output_type ?? "text",
    mcp_policy: step.mcp_policy ?? "inherit",
    input_bindings: step.input_bindings ?? null,
    input_contract: step.input_contract ?? null,
    output_contract: step.output_contract ?? null,
    input_config: step.input_config ?? null,
    output_config: step.output_config ?? null,
    output_classification_override: null,
    review_policy: step.review_policy ?? null
  }));
}

/**
 * Wrap a draft spec in a synthetic Flow for FlowGraph. The draft is not yet a
 * persisted flow, so the identity fields are placeholders the canvas never shows;
 * published_version stays null so the graph renders as an editable draft.
 */
export function draftSpecToFlow(spec: FlowDraftSpecCore): Flow {
  return {
    id: "",
    tenant_id: "",
    space_id: "",
    name: spec.flow_name,
    description: spec.flow_description ?? null,
    published_version: null,
    steps: planStepsToFlowSteps(spec.steps)
  };
}
