import { cleanup, render, screen } from "@testing-library/svelte";
import type { FlowStep } from "@eneo/eneo-js";
import { afterEach, describe, expect, it } from "vitest";
import { m } from "$lib/paraglide/messages";
import { syncDraftsFromStep } from "./advancedJsonDrafts";
import FlowStepAdvancedSection from "./FlowStepAdvancedSection.svelte";

afterEach(cleanup);

function renderSection(overrides: Partial<FlowStep> = {}) {
  const step: FlowStep = {
    id: "step-1",
    assistant_id: "assistant-1",
    step_order: 1,
    input_source: "flow_input",
    input_type: "text",
    output_mode: "pass_through",
    output_type: "json",
    input_contract: null,
    output_contract: null,
    ...overrides
  };
  const { drafts, errors } = syncDraftsFromStep(step);
  return render(FlowStepAdvancedSection, {
    step,
    isPublished: false,
    advancedJsonDrafts: drafts,
    advancedJsonErrors: errors
  });
}

describe("flow contract status", () => {
  it("shows contracts as inactive until a schema is configured", () => {
    renderSection();
    expect(screen.queryByText(m.flow_step_input_contract_active())).toBeNull();
    expect(screen.getAllByText(m.flow_step_input_contract_inactive())).toHaveLength(2);
  });

  it("shows configured contracts as active for supported input and output types", () => {
    renderSection({ input_contract: { type: "object" }, output_contract: { type: "object" } });
    expect(screen.getAllByText(m.flow_step_input_contract_active())).toHaveLength(2);
  });

  it("shows an inapplicable contract as inactive even when a schema remains", () => {
    renderSection({
      input_type: "audio",
      output_type: "text",
      input_contract: { type: "object" },
      output_contract: { type: "object" }
    });
    expect(screen.queryByText(m.flow_step_input_contract_active())).toBeNull();
    expect(screen.getAllByText(m.flow_step_input_contract_inactive())).toHaveLength(2);
  });
});
