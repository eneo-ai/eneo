import type { Flow, FlowStep } from "@eneo/eneo-js";

/** A complete flow step for a test; override what the test is about. */
export function flowStepFixture(overrides: Partial<FlowStep> = {}): FlowStep {
  return {
    id: "step-1",
    assistant_id: "assistant-1",
    step_order: 1,
    user_description: "Steg",
    input_source: "flow_input",
    input_type: "text",
    output_mode: "pass_through",
    output_type: "text",
    ...overrides
  } satisfies FlowStep;
}

/** A complete editable flow for a test, with the steps the test is about. */
export function flowFixture(overrides: Partial<Flow> = {}): Flow {
  return {
    id: "00000000-0000-0000-0000-000000000001",
    tenant_id: "tenant-1",
    space_id: "space-1",
    space_name: "Yta",
    name: "Flöde",
    description: null,
    published_version: null,
    draft_revision: 0,
    step_count: 0,
    metadata_json: null,
    run_history_retention: {
      state: "configured",
      effective_days: 30,
      mode: "preserve",
      source: "organization",
      contributors: { organization: { mode: "preserve", days: 30 }, space: null, flow: null }
    },
    created_at: null,
    updated_at: null,
    steps: [],
    ...overrides
  } satisfies Flow;
}
