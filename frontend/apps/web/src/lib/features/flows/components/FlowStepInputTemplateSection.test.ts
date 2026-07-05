// @vitest-environment jsdom

import { cleanup, render } from "@testing-library/svelte";
import type { ComponentProps } from "svelte";
import { afterEach, describe, expect, it } from "vitest";
import type { FlowStep } from "@eneo/eneo-js";

import { m } from "$lib/paraglide/messages";
import { getFlowStepUxCopy } from "$lib/features/flows/flowStepUxCopy";
import FlowStepInputTemplateSection from "./FlowStepInputTemplateSection.svelte";

afterEach(() => {
  cleanup();
});

function makeStep(stepOrder: number, overrides: Partial<FlowStep> = {}): FlowStep {
  return {
    id: `step-${stepOrder}`,
    assistant_id: `assistant-${stepOrder}`,
    step_order: stepOrder,
    user_description: `Step ${stepOrder}`,
    input_source: stepOrder === 1 ? "flow_input" : "previous_step",
    input_type: "text",
    output_mode: "pass_through",
    output_type: "text",
    mcp_policy: "inherit",
    ...overrides
  };
}

function renderSection(props: Partial<ComponentProps<typeof FlowStepInputTemplateSection>> = {}) {
  const step = makeStep(2, { user_description: "Skriv rapport" });
  return render(FlowStepInputTemplateSection, {
    props: {
      step,
      isPublished: false,
      isAdvancedMode: true,
      isPowerUser: true,
      hasInputTemplateOverride: false,
      hasTypedInputSources: false,
      showInputTemplate: false,
      inputTemplateText: "",
      effectiveInputSources: [],
      templateSourceConflict: null,
      templateStepRefs: [],
      steps: [makeStep(1, { user_description: "Läs dokument" }), step],
      formSchema: undefined,
      transcriptionEnabled: false,
      hasAudioInputSteps: false,
      stepUxCopy: getFlowStepUxCopy({ locale: "sv", inputSource: "previous_step" }),
      inputTemplateSectionTitle: "Underlag till steget",
      inputTemplateSectionDescription: "Beskrivning",
      ...props
    }
  });
}

describe("FlowStepInputTemplateSection", () => {
  it("renders typed source refs as effective underlag instead of an empty template", () => {
    const { container } = renderSection({
      hasTypedInputSources: true,
      effectiveInputSources: [
        {
          kind: "source_ref",
          stepRef: "step_1",
          sourceStepOrder: 1,
          sourceStepName: "Läs dokument",
          output: "text",
          fieldPath: null,
          label: "Original analys"
        }
      ]
    });

    expect(container.textContent).toContain(
      String(m.flow_input_template_effective_sources_title())
    );
    expect(container.textContent).toContain("Steg 1: Läs dokument");
    expect(container.textContent).toContain(String(m.flow_input_template_source_output_text()));
    expect(container.textContent).toContain("Original analys");
  });

  it("renders implicit previous-step underlag with the resolved source step", () => {
    const { container } = renderSection({
      effectiveInputSources: [
        {
          kind: "implicit_previous_step",
          sourceStepOrder: 1,
          sourceStepName: "Läs dokument"
        }
      ]
    });

    expect(container.textContent).toContain(
      String(m.flow_input_template_effective_sources_title())
    );
    expect(container.textContent).toContain("Steg 1: Läs dokument");
    expect(container.textContent).toContain(
      String(m.flow_input_template_effective_previous_step())
    );
  });

  it("renders deleted typed source refs without leaking the internal sentinel", () => {
    const { container } = renderSection({
      hasTypedInputSources: true,
      effectiveInputSources: [
        {
          kind: "deleted_source",
          stepRef: "step_1_deleted",
          deletedStepOrder: 1,
          output: "text",
          fieldPath: null,
          label: null
        }
      ]
    });

    expect(container.textContent).toContain("Steg 1");
    expect(container.textContent).toContain(String(m.flow_input_template_deleted_source_ref()));
    expect(container.textContent).not.toContain("step_1_deleted");
  });
});
