import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import ChunkSettings from "./ChunkSettings.svelte";
import ChunkSettingsFixture from "./ChunkSettingsFixture.svelte";

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
  it("submits the chunk pair whole once either field is customized", async () => {
    // Delegating source: the disclosure starts closed and both sides stay null.
    render(ChunkSettingsFixture, { chunkSize: null, chunkOverlap: null });
    const submitted = page.getByTestId("submitted");
    await expect.element(submitted).toHaveTextContent("size=null, overlap=null");

    // Opening the disclosure alone is not a customization, so the source keeps
    // following the deployment.
    await page.getByText(m.chunk_settings_customize()).click();
    await expect.element(submitted).toHaveTextContent("size=null, overlap=null");

    // Touching one field commits both. A size stored beside a null overlap changed
    // meaning whenever an operator retuned CHUNK_OVERLAP, which could hand ingestion
    // an overlap the API itself refuses.
    const slider = overlapSlider().element() as HTMLElement;
    slider.focus();
    slider.dispatchEvent(
      new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true, cancelable: true })
    );
    // One 5% step from the default 20% lands on the 25% ceiling: 50 of 200 tokens.
    // The size comes along even though nobody touched it — that is the contract.
    await expect.element(submitted).toHaveTextContent("size=200, overlap=50");
  });

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
