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
      stepUxCopy: getFlowStepUxCopy({ locale: "sv" }),
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
      m.flow_material_reads({ what: m.flow_material_what_sources() })
    );
    expect(container.textContent).toContain("Steg 1: Läs dokument");
    expect(container.textContent).toContain(String(m.flow_input_template_source_output_text()));
    expect(container.textContent).toContain("Original analys");
  });

  it("shows the implicit previous-step source as the material that will actually be used", () => {
    const { container } = renderSection();

    expect(container.textContent).toContain(
      m.flow_material_reads({
        what: m.flow_material_what_previous({
          step: `${m.flow_input_template_effective_step({ step: 1 })}: Läs dokument`
        })
      })
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

    await fireEvent.click(screen.getByRole("button", { name: /Välj resultat|Choose results/ }));
    expect(
      screen.getByRole("combobox", { name: m.flow_input_material_picker_search() })
    ).toBeTruthy();
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
    renderSection({ showInputTemplate: true });

    const materialHelp = screen.getByRole("button", {
      name: `${m.flow_settings_more_info({ title: m.flow_material_title() })}. ${m.flow_material_help()}`
    });
    expect(materialHelp.getAttribute("aria-describedby")).toBeNull();

    const customTextHelp = screen.getByRole("button", {
      name: `${m.flow_settings_more_info({ title: m.flow_material_own_text() })}. ${m.flow_input_template_help()}`
    });
    expect(customTextHelp.getAttribute("aria-describedby")).toBeNull();
  });

  it("uses distinct accessible relationships for each rendered step", () => {
    const first = renderSection({ showInputTemplate: true });
    const second = renderSection({ showInputTemplate: true });

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

  it("keeps an upload step's own text editable and warns when it leaves the upload out", () => {
    const uploadStep = makeStep(2, {
      user_description: "Skriv rapport",
      input_config: { runtime_input: { enabled: true, input_format: "document" } }
    });
    const upload = renderSection({
      step: uploadStep,
      runtimeInputEnabled: true,
      showInputTemplate: true
    });
    expect(upload.container.textContent).toContain(
      m.flow_material_reads({ what: m.flow_material_what_upload() })
    );
    expect(screen.getByRole("textbox")).toBeTruthy();
    cleanup();

    const leftOut = renderSection({
      step: { ...uploadStep, input_bindings: { question: "Namn: {{flow_input.namn}}" } as never },
      runtimeInputEnabled: true,
      hasInputTemplateOverride: true,
      inputTemplateText: "Namn: {{flow_input.namn}}"
    });
    expect(leftOut.container.textContent).toContain(m.flow_input_template_upload_left_out());
    cleanup();

    const kept = renderSection({
      step: {
        ...uploadStep,
        input_bindings: { question: "Transkript: {{step_input.text}}" } as never
      },
      runtimeInputEnabled: true,
      hasInputTemplateOverride: true,
      inputTemplateText: "Transkript: {{step_input.text}}"
    });
    expect(kept.container.textContent).not.toContain(m.flow_input_template_upload_left_out());
    expect(kept.container.textContent).toContain(
      m.flow_material_reads({ what: m.flow_material_what_own_text_with_upload() })
    );
  });

  it.each(["compose_text", "render_verbatim"] as const)(
    "says the step, not the AI, reads the material when the step does not call the AI (%s)",
    (output_mode) => {
      const { container } = renderSection({ step: makeStep(2, { output_mode }) });
      expect(container.textContent).toContain(m.flow_material_title_step());
      expect(container.textContent).not.toContain(m.flow_material_title());
    }
  );

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
