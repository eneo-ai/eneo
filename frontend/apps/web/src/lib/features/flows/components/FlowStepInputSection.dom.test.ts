import { cleanup, render, screen } from "@testing-library/svelte";
import { readable } from "svelte/store";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { FlowStep } from "@eneo/eneo-js";

import { getRuntimeInputConfig } from "$lib/features/flows/flowRuntimeInputConfig";
import { flowStepFixture } from "$lib/features/flows/flowStepTestFixture";
import { m } from "$lib/paraglide/messages";
import FlowStepInputSection from "./FlowStepInputSection.svelte";

// The tool section a tool step shows reads the space it is in.
vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({ state: { currentSpace: readable({ personal: false }) } })
}));

afterEach(() => {
  cleanup();
});

// Every step here has its own underlag: a question that would replace its source.
function renderSection(
  step: Pick<FlowStep, "output_mode" | "input_type" | "output_type">,
  question = "Sammanfatta {{flow_input.case_id}}"
) {
  return render(FlowStepInputSection, {
    props: {
      step: {
        id: "step-1",
        assistant_id: "assistant-1",
        step_order: 1,
        user_description: "Step 1",
        input_source: "flow_input",
        input_bindings: { question } as never,
        ...step
      },
      isPublished: false,
      isAdvancedMode: false,
      selectableInputSourceOptions: [{ value: "flow_input", legacyInvalid: false }],
      displayedInputTypeOptions: [
        { value: step.input_type, disabled: false, legacyInvalid: false }
      ],
      runtimeInputConfig: {} as never,
      sourceHintKind: null,
      sourceValidationMessage: null,
      inputSourceFeedback: null,
      inputTypeValidationMessage: null,
      inputTypeFeedback: null,
      transcriptionEnabled: true,
      transcriptionModelConfigured: true,
      transcriptionModelLabel: null
    }
  });
}

const sourceSelect = () => screen.getByLabelText(m.flow_step_section_input());

describe("FlowStepInputSection", () => {
  // Kills: a tool step offers "accept files when the flow runs", which the
  // server refuses beside a tool; a step with another source loses the
  // control; a tool step that already takes files cannot switch them off.
  it.each<{ source: FlowStep["input_source"]; uploads: boolean; offered: boolean }>([
    { source: "tool", uploads: false, offered: false },
    { source: "tool", uploads: true, offered: true },
    { source: "previous_step", uploads: false, offered: true }
  ])("offers uploads at run time: %o", ({ source, uploads, offered }) => {
    const step = flowStepFixture({
      input_source: source,
      input_config: uploads ? { runtime_input: { enabled: true, input_format: "document" } } : null
    });
    render(FlowStepInputSection, {
      props: {
        step,
        isPublished: false,
        isAdvancedMode: true,
        selectableInputSourceOptions: [],
        displayedInputTypeOptions: [],
        runtimeInputConfig: getRuntimeInputConfig(step),
        sourceHintKind: null,
        sourceValidationMessage: null,
        inputSourceFeedback: null,
        inputTypeValidationMessage: null,
        inputTypeFeedback: null,
        transcriptionEnabled: false,
        transcriptionModelConfigured: false,
        transcriptionModelLabel: null
      }
    });
    expect(
      screen.queryByRole("switch", { name: m.flow_runtime_input_accept_files() }) !== null
    ).toBe(offered);
  });

  // The source hint points at the section that overrides it, by the title the editor gives it.
  it("points a step with AI to the section the AI reads", () => {
    renderSection({ output_mode: "pass_through", input_type: "text", output_type: "text" });
    expect(sourceSelect().hasAttribute("disabled")).toBe(true);
    expect(
      screen.getByText(
        m.flow_step_input_source_underlag_decides({ section: m.flow_material_title() })
      )
    ).toBeTruthy();
  });

  it("points a step without AI to the section the step reads", () => {
    renderSection({ output_mode: "compose_text", input_type: "text", output_type: "text" });
    expect(sourceSelect().hasAttribute("disabled")).toBe(true);
    expect(
      screen.getByText(
        m.flow_step_input_source_underlag_decides({ section: m.flow_material_title_step() })
      )
    ).toBeTruthy();
  });

  // The editor shows a transcription no underlag section, but a binding set elsewhere
  // (for example by the AI builder) still replaces its source at run time.
  it("keeps a bound transcription's source locked without pointing to a section it lacks", () => {
    renderSection(
      { output_mode: "transcribe_only", input_type: "audio", output_type: "text" },
      "{{step_input.text}}"
    );
    expect(sourceSelect().hasAttribute("disabled")).toBe(true);
    expect(screen.getByText(m.flow_step_input_source_underlag_decides_unshown())).toBeTruthy();
  });

  // Switching a step to template fill keeps its underlag, which the template ignores.
  it("leaves a template fill's source in charge despite a leftover underlag", () => {
    renderSection({ output_mode: "template_fill", input_type: "text", output_type: "docx" });
    expect(sourceSelect().hasAttribute("disabled")).toBe(false);
    expect(screen.queryByText(/Används inte just nu|Not used right now/)).toBeNull();
  });
});
