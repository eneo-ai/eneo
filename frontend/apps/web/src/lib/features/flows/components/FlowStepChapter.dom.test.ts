import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it } from "vitest";

import FlowStepChapter from "./FlowStepChapter.svelte";

afterEach(() => {
  cleanup();
});

describe("FlowStepChapter", () => {
  it("remembers the user's open state for each step during the session", async () => {
    const { rerender } = render(FlowStepChapter, {
      title: "Uppgift",
      initialOpen: true,
      resetKey: 1
    });
    const trigger = screen.getByRole("button", { name: "Uppgift" });

    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    await fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("false");

    await rerender({ title: "Uppgift", initialOpen: true, resetKey: 2 });
    expect(trigger.getAttribute("aria-expanded")).toBe("true");

    await rerender({ title: "Uppgift", initialOpen: true, resetKey: 1 });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
  });
});
