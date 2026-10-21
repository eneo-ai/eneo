import type { FlowPublic, FlowStep } from "./flows-api";

/** A saved step: `order` is its 1-based place, the id and assistant follow from it. */
export function makeStep(order: number, overrides: Partial<FlowStep> = {}): FlowStep {
  return {
    id: `step-${order}`,
    assistant_id: `assistant-${order}`,
    step_order: order,
    user_description: `Steg nummer ${order}`,
    input_source: order === 1 ? "flow_input" : "previous_step",
    input_type: "text",
    output_mode: "pass_through",
    output_type: "text",
    ...overrides
  };
}

export function makeFlow(overrides: Partial<FlowPublic> = {}): FlowPublic {
  const steps = overrides.steps ?? [
    makeStep(1, { user_description: "Sammanfatta" }),
    makeStep(2, { user_description: "Skriv svar" })
  ];
  return {
    id: "flow-1",
    name: "Medborgarbrev",
    description: "Sammanfattar och besvarar brev.",
    draft_revision: 4,
    published_version: null,
    space_id: "space-1",
    space_name: "Upphandling",
    tenant_id: "tenant-1",
    step_count: steps.length,
    metadata_json: null,
    run_history_retention: { source: "none" },
    ...overrides,
    steps
  } as FlowPublic;
}
