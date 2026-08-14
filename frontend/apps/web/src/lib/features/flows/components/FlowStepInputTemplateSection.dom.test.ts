import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import type { ComponentProps } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FlowStep } from "@eneo/eneo-js";

import { m } from "$lib/paraglide/messages";
import { getFlowStepUxCopy } from "$lib/features/flows/flowStepUxCopy";
import FlowStepInputTemplateSection from "./FlowStepInputTemplateSection.svelte";

afterEach(() => {
  cleanup();
});

beforeEach(() => {
  Object.defineProperty(Element.prototype, "scrollIntoView", {
    configurable: true,
    value: vi.fn()
  });
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
      showInputTemplate: false,
      inputTemplateText: "",
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
    const step = makeStep(2, {
      user_description: "Skriv rapport",
      input_bindings: {
        source_refs: [{ step_ref: "step_1", output: "text", label: "Original analys" }]
      } as never
    });
    const { container } = renderSection({
      step,
      steps: [makeStep(1, { user_description: "Läs dokument" }), step]
    });

    expect(container.textContent).toContain(
      String(m.flow_input_template_effective_sources_title())
    );
    expect(container.textContent).toContain("Steg 1: Läs dokument");
    expect(container.textContent).toContain(String(m.flow_input_template_source_output_text()));
    expect(container.textContent).toContain("Original analys");
  });

  it("shows the implicit previous-step source as the material that will actually be used", () => {
    const { container } = renderSection();

    expect(container.textContent).toContain(
      String(m.flow_input_template_effective_sources_title())
    );
    expect(container.textContent).toContain(
      String(m.flow_input_template_effective_previous_step())
    );
  });

  it("lets the user choose a contract-backed JSON field as text material", async () => {
    const onInputSourcesChange = vi.fn();
    const sourceStep = makeStep(1, {
      user_description: "Strukturera samtalet",
      output_type: "json",
      output_contract: {
        type: "object",
        properties: {
          summary: { type: "string", description: "Kort sammanfattning" }
        }
      }
    });
    const step = makeStep(2, { user_description: "Skriv rapport" });
    renderSection({
      step,
      steps: [sourceStep, step],
      onInputSourcesChange
    });

    await fireEvent.click(screen.getByRole("button", { name: /Ändra underlag|Change material/ }));
    await fireEvent.click(screen.getByText("summary"));

    expect(onInputSourcesChange).toHaveBeenCalledWith({
      sourceRefs: [
        {
          stepRef: "step_1",
          output: "structured",
          fieldPath: "summary",
          label: null,
          itemTemplate: null
        }
      ]
    });
    await fireEvent.click(screen.getByRole("button", { name: /Klar|Done/ }));
  });

  it("renders deleted typed source refs without leaking the internal sentinel", () => {
    const step = makeStep(2, {
      input_bindings: {
        source_refs: [{ step_ref: "step_1_deleted", output: "text" }]
      } as never
    });
    const { container } = renderSection({
      step
    });

    expect(container.textContent).toContain("Steg 1");
    expect(container.textContent).toContain(String(m.flow_input_template_deleted_source_ref()));
    expect(container.textContent).not.toContain("step_1_deleted");
  });

  it("explains material and custom text through keyboard-focusable help controls", () => {
    renderSection();

    const materialHelp = screen.getByRole("button", {
      name: `${m.flow_settings_more_info({
        title: m.flow_input_template_effective_sources_title()
      })}. ${m.flow_input_material_help()}`
    });
    expect(materialHelp.getAttribute("aria-describedby")).toBeNull();

    const customTextHelp = screen.getByRole("button", {
      name: `${m.flow_settings_more_info({ title: "Underlag till steget" })}. ${m.flow_input_template_help()}`
    });
    expect(customTextHelp.getAttribute("aria-describedby")).toBeNull();
  });

  it("uses distinct accessible relationships for each rendered step", () => {
    const first = renderSection();
    const second = renderSection();

    const labelledSections = [first.container, second.container].map((container) =>
      container.querySelector("section[aria-labelledby]")
    );
    const titleIds = labelledSections.map((section) => section?.getAttribute("aria-labelledby"));

    expect(titleIds.every(Boolean)).toBe(true);
    expect(new Set(titleIds).size).toBe(2);
    for (const [index, titleId] of titleIds.entries()) {
      expect(
        [...[first.container, second.container][index].querySelectorAll("[id]")].some(
          (element) => element.id === titleId
        )
      ).toBeTruthy();
    }
  });

  it("shows JSON-coupled material without offering a misleading text-source editor", () => {
    const step = makeStep(2, {
      input_type: "json",
      input_contract: {
        type: "object",
        properties: { summary: { type: "string" } },
        required: ["summary"]
      }
    });
    renderSection({ step, showInputTemplate: true });

    expect(screen.getByText(String(m.flow_input_material_json_locked_notice()))).toBeTruthy();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(
      screen.queryByRole("button", { name: String(m.flow_input_material_change()) })
    ).toBeNull();
  });

  it("shows runtime material as locked instead of exposing an empty custom-text editor", () => {
    renderSection({ runtimeInputEnabled: true, showInputTemplate: true });

    expect(screen.getByText(String(m.flow_input_material_runtime_locked_notice()))).toBeTruthy();
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("keeps custom text available for document input without a JSON input contract", () => {
    const step = makeStep(2, { input_type: "document" });
    renderSection({ step, showInputTemplate: true });

    expect(screen.getByRole("textbox")).toBeTruthy();
  });

  it("explains why earlier results cannot be selected for a non-text input type", () => {
    const step = makeStep(2, { input_type: "any" });
    renderSection({ step, showInputTemplate: true });

    expect(
      screen.getByText(String(m.flow_input_material_source_type_locked_notice()))
    ).toBeTruthy();
    expect(screen.getByRole("textbox")).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: String(m.flow_input_material_change()) })
    ).toBeNull();
  });

  it("fails closed when a saved binding contains fields this editor does not understand", () => {
    const step = makeStep(2, { input_bindings: { hidden_mode: true } as never });
    renderSection({ step, showInputTemplate: true });

    expect(screen.getByText(String(m.flow_input_material_invalid_notice()))).toBeTruthy();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(
      screen.queryByRole("button", { name: String(m.flow_input_material_change()) })
    ).toBeNull();
  });

  it("preserves custom text when the user clears selected material sources", async () => {
    const onInputSourcesChange = vi.fn();
    const step = makeStep(2, {
      input_bindings: {
        question: "Skriv en rapport.",
        source_refs: [{ step_ref: "step_1", output: "text" }]
      } as never
    });
    renderSection({
      step,
      onInputSourcesChange
    });

    await fireEvent.click(
      screen.getByRole("button", { name: String(m.flow_input_material_clear_sources()) })
    );

    expect(onInputSourcesChange).toHaveBeenCalledWith({ sourceRefs: [] });
  });

  it("keeps published material visible without exposing mutation controls", () => {
    const step = makeStep(2, {
      input_bindings: {
        source_refs: [{ step_ref: "step_1", output: "text" }]
      } as never
    });
    renderSection({
      step,
      isPublished: true
    });

    expect(screen.getByText("Steg 1: Läs dokument")).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: String(m.flow_input_material_change()) })
    ).toBeNull();
    expect(
      screen.queryByRole("button", {
        name: String(m.flow_input_material_remove({ source: "Steg 1: Läs dokument" }))
      })
    ).toBeNull();
  });

  it("shows advanced source formatting without letting the simplified editor rewrite it", () => {
    const step = makeStep(2, {
      output_mode: "compose_text",
      input_bindings: {
        source_refs: [
          {
            step_ref: "step_1",
            output: "structured",
            field_path: "participants",
            item_template: "- {name}"
          }
        ]
      } as never
    });
    renderSection({ step });

    expect(screen.getByText(String(m.flow_input_material_advanced_notice()))).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: String(m.flow_input_material_change()) })
    ).toBeNull();
  });

  it("flags item formatting that the selected output mode cannot use", () => {
    const step = makeStep(2, {
      output_mode: "pass_through",
      input_bindings: {
        source_refs: [
          {
            step_ref: "step_1",
            output: "structured",
            field_path: "participants",
            item_template: "- {name}"
          }
        ]
      } as never
    });
    renderSection({ step });

    expect(
      screen.getByText(String(m.flow_input_material_item_template_unsupported_notice()))
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: String(m.flow_input_material_change()) })
    ).toBeNull();
  });
});
