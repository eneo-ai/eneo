import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { readable } from "svelte/store";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { FlowStep } from "@eneo/eneo-js";

import { getRuntimeInputConfig } from "$lib/features/flows/flowRuntimeInputConfig";
import { flowStepFixture } from "$lib/features/flows/flowStepTestFixture";
import { m } from "$lib/paraglide/messages";
import { getInputSourceLabel } from "./flowStepEditHelpers";
import FlowStepInputSection from "./FlowStepInputSection.svelte";
import type { FlowToolOption } from "./tool/toolInputConfig";

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
      selectableInputSourceOptions: [
        { value: "flow_input", legacyInvalid: false, advancedOnly: false }
      ],
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

  // Kills: a step with another source shows a tool section, or its source,
  // material type, reading choice and uploads change order.
  it("keeps the order of a step that does not read a tool", () => {
    const step = flowStepFixture({ step_order: 2, input_source: "previous_step" });
    render(FlowStepInputSection, {
      props: {
        step,
        isPublished: false,
        isAdvancedMode: true,
        selectableInputSourceOptions: [
          { value: "previous_step", legacyInvalid: false, advancedOnly: false }
        ],
        displayedInputTypeOptions: [{ value: "text", disabled: false, legacyInvalid: false }],
        runtimeInputConfig: getRuntimeInputConfig(step),
        sourceHintKind: "previous_step_text",
        sourceValidationMessage: null,
        inputSourceFeedback: null,
        inputTypeValidationMessage: null,
        inputTypeFeedback: null,
        transcriptionEnabled: false,
        transcriptionModelConfigured: false,
        transcriptionModelLabel: null
      }
    });

    expect(screen.queryByText(m.flow_tool_picker_title())).toBeNull();
    const inOrder = [
      sourceSelect(),
      screen.getByLabelText(m.flow_step_input_type()),
      screen.getByRole("radiogroup", { name: m.flow_reading_mode_title() }),
      screen.getByRole("switch", { name: m.flow_runtime_input_accept_files() })
    ];
    for (const [index, element] of inOrder.slice(1).entries()) {
      expect(
        inOrder[index].compareDocumentPosition(element) & Node.DOCUMENT_POSITION_FOLLOWING
      ).toBeTruthy();
    }
  });

  // Kills: Enkel hides the tool source without a word, or lets it be chosen there.
  it("lists the tool source in Enkel as one to choose in Avancerad", async () => {
    const step = flowStepFixture({ input_source: "flow_input" });
    render(FlowStepInputSection, {
      props: {
        step,
        isPublished: false,
        isAdvancedMode: false,
        selectableInputSourceOptions: [
          { value: "flow_input", legacyInvalid: false, advancedOnly: false },
          { value: "tool", legacyInvalid: false, advancedOnly: true }
        ],
        displayedInputTypeOptions: [],
        runtimeInputConfig: getRuntimeInputConfig(step),
        sourceHintKind: "flow_input",
        sourceValidationMessage: null,
        inputSourceFeedback: null,
        inputTypeValidationMessage: null,
        inputTypeFeedback: null,
        transcriptionEnabled: false,
        transcriptionModelConfigured: false,
        transcriptionModelLabel: null
      }
    });

    // bits-ui's select needs these, which jsdom does not implement.
    Element.prototype.hasPointerCapture ??= () => false;
    Element.prototype.releasePointerCapture ??= () => {};
    Element.prototype.scrollIntoView ??= () => {};
    await fireEvent.pointerDown(sourceSelect(), { button: 0, pointerType: "mouse" });
    const tool = await screen.findByRole("option", {
      name: new RegExp(getInputSourceLabel("tool"))
    });
    expect(tool.hasAttribute("data-disabled")).toBe(true);
    expect(tool.textContent).toContain(m.flow_step_option_in_advanced());
  });

  describe("with a tool as source", () => {
    const SEARCH: FlowToolOption = {
      mcp_server_id: "server-1",
      mcp_server_name: "Ärenden",
      mcp_server_security_level: null,
      tool_id: "tool-search",
      tool_name: "search_cases",
      tool_description: "Söker ärenden.",
      input_schema: { type: "object", properties: { query: { type: "string" } } },
      refusal: null
    };

    function renderToolStep(inputType: FlowStep["input_type"]) {
      const step = flowStepFixture({
        input_source: "tool",
        input_type: inputType,
        input_config: { tool: { mcp_server_id: "server-1", tool_id: "tool-search", arguments: {} } }
      });
      render(FlowStepInputSection, {
        props: {
          step,
          isPublished: false,
          isAdvancedMode: true,
          selectableInputSourceOptions: [
            { value: "tool", legacyInvalid: false, advancedOnly: false }
          ],
          displayedInputTypeOptions: ["text", "json"].map((value) => ({
            value,
            disabled: false,
            legacyInvalid: false
          })),
          runtimeInputConfig: getRuntimeInputConfig(step),
          sourceHintKind: "tool_source",
          sourceValidationMessage: null,
          inputSourceFeedback: null,
          inputTypeValidationMessage: null,
          inputTypeFeedback: null,
          transcriptionEnabled: false,
          transcriptionModelConfigured: false,
          transcriptionModelLabel: null,
          toolOptions: {
            status: "loaded",
            options: [SEARCH],
            classificationsEnabled: false,
            refreshing: false
          }
        }
      });
    }

    // Kills: the picker and its arguments come after the material type and the
    // reading choice, away from the source that asked for them.
    it("puts the tool and its arguments right under the source", () => {
      renderToolStep("text");

      const inOrder = [
        sourceSelect(),
        screen.getByRole("combobox", { name: /search_cases/ }),
        screen.getByRole("group", { name: "query" }),
        screen.getByLabelText(m.flow_step_input_type()),
        screen.getByRole("radiogroup", { name: m.flow_reading_mode_title() })
      ];
      for (const [index, element] of inOrder.slice(1).entries()) {
        expect(
          inOrder[index].compareDocumentPosition(element) & Node.DOCUMENT_POSITION_FOLLOWING
        ).toBeTruthy();
      }
    });

    // Kills: the material type of a tool step does not say what it means for
    // the tool's answer, or says the other type's rule.
    it.each([
      { inputType: "text" as const, rule: () => m.flow_step_input_format_help_tool_text() },
      { inputType: "json" as const, rule: () => m.flow_step_input_format_help_tool_json() }
    ])("says how a $inputType step takes the tool's answer", ({ inputType, rule }) => {
      renderToolStep(inputType);

      expect(screen.getByText(m.flow_step_input_type_tool_desc())).toBeTruthy();
      const rules = [
        m.flow_step_input_format_help_tool_text(),
        m.flow_step_input_format_help_tool_json()
      ];
      expect(rules.filter((text) => screen.queryByText(text) !== null)).toStrictEqual([rule()]);
    });
  });
});
