import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it } from "vitest";

import FlowStepChapter from "./FlowStepChapter.svelte";
import { createRawSnippet } from "svelte";

afterEach(() => {
  cleanup();
});

describe("FlowStepChapter", () => {
  it("removes closed chapter controls from keyboard and accessibility navigation during the closing animation", async () => {
    render(FlowStepChapter, {
      title: "Result",
      initialOpen: true,
      children: createRawSnippet(() => ({
        render: () => '<button type="button">Text source</button>'
      }))
    });
    const source = screen.getByRole("button", { name: "Text source" });
    const content = source.closest('[data-slot="collapsible-content"]');
    await fireEvent.click(screen.getByRole("button", { name: "Result" }));
    expect(content?.hasAttribute("inert")).toBe(true);
    expect(screen.queryByRole("button", { name: "Text source" })).toBeNull();
  });
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
