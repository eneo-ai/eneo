// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { FlowStep } from "@intric/intric-js";

import FlowPromptEditor from "./FlowPromptEditor.svelte";

afterEach(() => {
  cleanup();
});

describe("FlowPromptEditor", () => {
  it("shows custom input fields as canonical flow_input tokens", async () => {
    const onChange = vi.fn();
    const onCommit = vi.fn();

    render(FlowPromptEditor, {
      value: "",
      steps: [],
      currentStepOrder: 1,
      transcriptionEnabled: false,
      formSchema: {
        fields: [{ name: "user_flow", type: "text" }]
      },
      onChange,
      onCommit
    });

    const chip = screen.getByRole("button", { name: "{{flow_input.user_flow}}" });
    await fireEvent.click(chip);

    expect(onChange).toHaveBeenCalledWith("{{flow_input.user_flow}}");
    expect(onCommit).toHaveBeenCalledWith("{{flow_input.user_flow}}");
  });

  it("reports previous-step variable inserts as ordinary text changes", async () => {
    const onChange = vi.fn();
    const onCommit = vi.fn();
    const previousStep = {
      id: "step-4",
      assistant_id: "assistant-4",
      step_order: 4,
      user_description: "Skapa utkast",
      input_source: "previous_step",
      input_type: "text",
      output_mode: "pass_through",
      output_type: "text",
      mcp_policy: "inherit"
    } as FlowStep;

    render(FlowPromptEditor, {
      value: "",
      steps: [previousStep],
      currentStepOrder: 5,
      transcriptionEnabled: false,
      formSchema: undefined,
      isAdvancedMode: true,
      onChange,
      onCommit
    });

    await fireEvent.click(screen.getByTitle(/@ för genväg/));
    await fireEvent.click(await screen.findByText("Textutdata"));

    expect(onChange).toHaveBeenCalledWith("{{step_4.output.text}}");
    expect(onCommit).toHaveBeenCalledWith("{{step_4.output.text}}");
  });
});
