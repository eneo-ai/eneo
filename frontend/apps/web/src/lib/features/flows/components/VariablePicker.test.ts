// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import VariablePicker from "./VariablePicker.svelte";

afterEach(() => {
  cleanup();
});

describe("VariablePicker", () => {
  it("inserts custom form fields through the canonical flow_input namespace", async () => {
    const onInsert = vi.fn();

    render(VariablePicker, {
      steps: [],
      currentStepOrder: 1,
      formSchema: {
        fields: [{ name: "kundnamn", type: "text" }]
      },
      onInsert
    });

    await fireEvent.click(screen.getByTitle(/@ för genväg/));
    await fireEvent.click(await screen.findByText("kundnamn"));

    expect(onInsert).toHaveBeenCalledWith("{{flow_input.kundnamn}}");
  });
});
