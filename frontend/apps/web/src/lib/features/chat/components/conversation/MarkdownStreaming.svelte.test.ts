import { render } from "vitest-browser-svelte";
import { describe, expect, it } from "vitest";
import { marked } from "marked";
import { Markdown } from "@eneo/ui";
import InrefProbe from "./__fixtures__/InrefProbe.svelte";

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

  it("remounts a citation renderer when the reference at a position changes", async () => {
    const { container, rerender } = render(Markdown, {
      source: 'Se <inref id="doc-a"/> för mer',
      customRenderers: { inref: InrefProbe }
    });
    const probe = () => container.querySelector("[data-inref-probe]") as HTMLElement;
    const initial = probe();
    expect(initial.dataset.mounted).toBe("doc-a");

    // Streaming more text keeps the very same renderer element, not a remount.
    await rerender({ source: 'Se <inref id="doc-a"/> för mer information.' });
    expect(probe()).toBe(initial);
    expect(probe().dataset.mounted).toBe("doc-a");

    // Another conversation's answer at the same position gets a fresh one.
    await rerender({ source: 'Se <inref id="doc-b"/> för mer' });
    expect(probe().dataset.current).toBe("doc-b");
    expect(probe().dataset.mounted).toBe("doc-b");
  });

  it("keeps its extensions private to the component instead of the global marked", async () => {
    for (let i = 0; i < 25; i++) {
      render(Markdown, { source: `Message ${i} with <inref id="ref-${i}"/>` });
    }
    // The global instance never receives the eneo extensions (or grows per mount).
    expect(marked.defaults.extensions ?? null).toBeNull();
    expect(JSON.stringify(marked.lexer('Text <inref id="doc-z"/>'))).not.toContain("eneoInref");
    // ...while the component still recognises citations.
    const { container } = render(Markdown, {
      source: 'Text <inref id="doc-z"/>',
      customRenderers: { inref: InrefProbe }
    });
    const probe = container.querySelector("[data-inref-probe]") as HTMLElement | null;
    expect(probe?.dataset.current).toBe("doc-z");
  });
});
