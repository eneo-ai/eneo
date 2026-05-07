// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import FlowPromptEditor from "./FlowPromptEditor.svelte";

afterEach(() => {
  cleanup();
});

describe("FlowPromptEditor", () => {
  it("shows custom input fields as canonical flow_input tokens", async () => {
    const onCommit = vi.fn();

    render(FlowPromptEditor, {
      value: "",
      steps: [],
      currentStepOrder: 1,
      transcriptionEnabled: false,
      formSchema: {
        fields: [{ name: "user_flow", type: "text" }]
      },
      onCommit
    });

    const chip = screen.getByRole("button", { name: "{{flow_input.user_flow}}" });
    await fireEvent.click(chip);

    expect(onCommit).toHaveBeenCalledWith("{{flow_input.user_flow}}");
  });
});
