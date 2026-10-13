import type { FlowStep } from "@eneo/eneo-js";

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
