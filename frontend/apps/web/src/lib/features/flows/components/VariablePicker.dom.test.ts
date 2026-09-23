import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import VariablePicker from "./VariablePicker.svelte";

// The command list scrolls the active option into view, which jsdom lacks.
beforeAll(() => {
  Element.prototype.scrollIntoView ??= vi.fn();
});

afterEach(async () => {
  cleanup();
  await vi.waitFor(() => {
    expect(document.body.style.overflow).not.toBe("hidden");
  });
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

    await fireEvent.click(
      screen.getByRole("button", { name: /^(Infoga variabel|Insert variable)$/ })
    );
    await fireEvent.click(await screen.findByRole("option", { name: /kundnamn/ }));

    expect(onInsert).toHaveBeenCalledWith("{{flow_input.kundnamn}}");
  });

  it("offers the section number only on a step that reads section by section", async () => {
    const { unmount } = render(VariablePicker, {
      steps: [],
      currentStepOrder: 1,
      formSchema: undefined,
      sectionVariablesAvailable: true,
      onInsert: vi.fn()
    });
    await fireEvent.click(
      screen.getByRole("button", { name: /^(Infoga variabel|Insert variable)$/ })
    );
    expect(
      await screen.findByRole("option", { name: /Delens nummer|Section number/ })
    ).toBeTruthy();
    unmount();

    render(VariablePicker, {
      steps: [],
      currentStepOrder: 1,
      formSchema: { fields: [{ name: "kundnamn", type: "text" }] },
      onInsert: vi.fn()
    });
    await fireEvent.click(
      screen.getByRole("button", { name: /^(Infoga variabel|Insert variable)$/ })
    );
    await screen.findByRole("option", { name: /kundnamn/ });
    expect(screen.queryByRole("option", { name: /Delens nummer|Section number/ })).toBeNull();
  });
});
