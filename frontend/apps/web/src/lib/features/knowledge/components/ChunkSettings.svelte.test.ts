import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import ChunkSettings from "./ChunkSettings.svelte";

// The component reads the platform chunking policy from the backend-provided app
// context. These are the shipped defaults, so the assertions below describe what a
// stock deployment renders.
vi.mock("$lib/core/AppContext", () => ({
  getAppContext: () => ({
    settings: {
      chunking: {
        default_chunk_size: 200,
        default_chunk_overlap: 40,
        min_chunk_size: 50,
        max_chunk_size: 100000,
        max_chunk_fraction: 0.6,
        max_overlap_fraction: 0.25
      }
    }
  })
}));

// The suite renders components without the app stylesheet, so the slider's track and
// thumb have no intrinsic size and count as hidden. Role and accessible name are what
// this test is about, so it matches those without also requiring visibility.
const overlapSlider = () =>
  page.getByRole("slider", { name: m.chunk_overlap_label(), includeHidden: true });

describe("ChunkSettings", () => {
  it("gives the overlap slider a localized accessible name", async () => {
    // An explicit override starts the disclosure expanded.
    render(ChunkSettings, { chunkSize: 400, chunkOverlap: 40 });

    // Found by role and name: the visible paragraph beside the track is not
    // programmatically associated with the thumb, so only a name on the control
    // itself makes it identifiable to a screen reader.
    await expect.element(overlapSlider()).toBeInTheDocument();
  });

  it("keeps the labelled slider keyboard-adjustable", async () => {
    render(ChunkSettings, { chunkSize: 400, chunkOverlap: 40 });

    // 40 of 400 tokens is 10%.
    await expect
      .element(page.getByText(m.chunk_overlap_value({ percent: 10, tokens: 40 })))
      .toBeInTheDocument();

    const thumb = overlapSlider().element() as HTMLElement;
    thumb.focus();
    thumb.dispatchEvent(
      new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true, cancelable: true })
    );

    // One 5% step. Reaching the displayed value proves onInput fired: the mount guard
    // in Slider suppresses programmatic prop syncs, and would suppress this too if it
    // could not tell real input apart.
    await expect
      .element(page.getByText(m.chunk_overlap_value({ percent: 15, tokens: 60 })))
      .toBeInTheDocument();
  });
});
