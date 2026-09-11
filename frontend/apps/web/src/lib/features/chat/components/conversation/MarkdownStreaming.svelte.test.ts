import { render } from "vitest-browser-svelte";
import { describe, expect, it } from "vitest";
import { Markdown } from "@eneo/ui";

// The chat appends streamed text to the answer every buffered flush. The
// markdown tree must patch the blocks that already exist instead of rebuilding
// them, or long answers get slower with every flush.
describe("Markdown while streaming", () => {
  it("keeps the rendered blocks and only patches the text that changed", async () => {
    const { container, rerender } = render(Markdown, {
      source: "# Title\n\nFirst paragraph.\n\n- one\n- tw"
    });

    const heading = container.querySelector("h1");
    const paragraph = container.querySelector("p");
    const list = container.querySelector("ul");
    expect(heading?.textContent).toBe("Title");
    expect(list?.textContent).toContain("tw");

    await rerender({
      source: "# Title\n\nFirst paragraph.\n\n- one\n- two\n\nSecond paragraph."
    });

    expect(container.querySelector("h1")).toBe(heading);
    expect(container.querySelector("p")).toBe(paragraph);
    expect(container.querySelector("ul")).toBe(list);
    expect(container.querySelectorAll("li")[1]?.textContent).toBe("two");
    expect(container.querySelectorAll("p")[1]?.textContent).toBe("Second paragraph.");
  });
});
