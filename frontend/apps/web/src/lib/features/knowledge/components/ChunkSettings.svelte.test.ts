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

    // Touching one field commits both — customisation is pair-level.
    const slider = overlapSlider().element() as HTMLElement;
    slider.focus();
    slider.dispatchEvent(
      new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true, cancelable: true })
    );
    // One 5% step from the default 20% lands on the 25% ceiling: 50 of 200 tokens.
    await expect.element(submitted).toHaveTextContent("size=200, overlap=50");
  });

  it("respects the model ceiling when only the overlap is customized", async () => {
    // max_input 300 puts the ceiling at floor(300 * 0.6) = 180, below the 200 default.
    render(ChunkSettingsFixture, { chunkSize: null, chunkOverlap: null, maxInput: 300 });
    const submitted = page.getByTestId("submitted");

    await page.getByText(m.chunk_settings_customize()).click();
    await expect.element(submitted).toHaveTextContent("size=null, overlap=null");

    // Touching only the overlap still submits a size, so the ceiling applies to it.
    const slider = overlapSlider().element() as HTMLElement;
    slider.focus();
    slider.dispatchEvent(
      new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true, cancelable: true })
    );

    await expect.element(submitted).toHaveTextContent("size=180, overlap=45");
    // And the size the editor displays is the size it submits.
    await expect.element(page.getByRole("spinbutton")).toHaveValue(180);
  });

  it("announces the overlap as tokens, not as the slider's percentage", async () => {
    // 40 of 400 tokens is 10%; announcing the thumb's bare 10 would name the wrong unit.
    render(ChunkSettings, { chunkSize: 400, chunkOverlap: 40 });

    const expected = m.chunk_overlap_value({ percent: 10, tokens: 40 });
    await expect.element(overlapSlider()).toHaveAttribute("aria-valuetext", expected);

    const thumb = overlapSlider().element() as HTMLElement;
    thumb.focus();
    thumb.dispatchEvent(
      new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true, cancelable: true })
    );

    // And it keeps up with the value, rather than being a one-time mount string.
    await expect
      .element(overlapSlider())
      .toHaveAttribute("aria-valuetext", m.chunk_overlap_value({ percent: 15, tokens: 60 }));
  });

  it("does not smuggle a below-minimum size back from a low-limit model", async () => {
    const { rerender } = render(ChunkSettingsFixture, {
      chunkSize: null,
      chunkOverlap: null,
      maxInput: 1000
    });
    const submitted = page.getByTestId("submitted");
    await page.getByText(m.chunk_settings_customize()).click();

    // Customize only the overlap. The size comes along at the platform default.
    const thumb = () => overlapSlider().element() as HTMLElement;
    thumb().focus();
    thumb().dispatchEvent(
      new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true, cancelable: true })
    );
    await expect.element(submitted).toHaveTextContent("size=200, overlap=50");

    // A model that caps chunks at floor(64 * 0.6) = 38, below the API's floor of 50.
    // Nothing explicit can be honoured, so the pair returns to delegation.
    await rerender({ maxInput: 64 });
    await expect.element(submitted).toHaveTextContent("size=null, overlap=null");

    // Back to a roomy model: the clamped 38 must not reappear (the API refuses it).
    await rerender({ maxInput: 1000 });
    await expect.element(submitted).toHaveTextContent("size=null, overlap=null");
  });

  it("warns about the re-index cost only when the source already holds content", async () => {
    // Creating a source: nothing is stored yet, so configuring it costs nothing.
    render(ChunkSettings, { chunkSize: 400, chunkOverlap: 40 });
    await expect.element(page.getByText(m.chunk_settings_reembed_note())).toBeInTheDocument();
    await expect
      .element(page.getByText(m.chunk_settings_reindex_warning_title()))
      .not.toBeInTheDocument();
  });

  it("names the cost when editing a source that already holds content", async () => {
    render(ChunkSettings, {
      chunkSize: 400,
      chunkOverlap: 40,
      hasIndexedContent: true
    });

    await expect
      .element(page.getByText(m.chunk_settings_reindex_warning_title()))
      .toBeInTheDocument();
    await expect.element(page.getByText(m.chunk_settings_reembed_note())).not.toBeInTheDocument();
  });

  it("gives the overlap slider a localized accessible name", async () => {
    // An explicit override starts the disclosure expanded.
    render(ChunkSettings, { chunkSize: 400, chunkOverlap: 40 });

    // Found by role and name — the visible text beside the track is not
    // programmatically associated with the thumb.
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

    // Reaching the displayed value proves onInput fired despite Slider's mount guard.
    await expect
      .element(page.getByText(m.chunk_overlap_value({ percent: 15, tokens: 60 })))
      .toBeInTheDocument();
  });
});
