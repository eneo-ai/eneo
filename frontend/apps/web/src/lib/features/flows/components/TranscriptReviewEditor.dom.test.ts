import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/svelte";
import { afterEach, it, expect, vi } from "vitest";
import Fixture from "./TranscriptReviewEditor.fixture.svelte";
import Editor from "./TranscriptReviewEditor.svelte";
import { assignSelection } from "../transcriptReviewEditor";
import type { TranscriptSegment } from "../transcriptSegments";

// The menu primitive needs pointer capture, animation and scrolling, which jsdom omits.
Element.prototype.animate ??= (() => ({
  cancel() {},
  finished: Promise.resolve(),
  onfinish: null
})) as never;
Element.prototype.hasPointerCapture ??= () => false;
Element.prototype.setPointerCapture ??= () => undefined;
Element.prototype.releasePointerCapture ??= () => undefined;
Object.defineProperty(Element.prototype, "scrollIntoView", { configurable: true, value: () => {} });

const press = async (element: HTMLElement) => {
  await fireEvent.pointerDown(element, { pointerType: "mouse", button: 0 });
  await fireEvent.pointerUp(element, { pointerType: "mouse", button: 0 });
  await fireEvent.click(element);
};

/**
 * Assigning is a menu action, not a value: open the menu, then pick the speaker.
 * Opened from the keyboard, which is both what the menu primitive responds to in
 * jsdom and the path this control exists to make work.
 */
const assignTo = async (speaker: string) => {
  await fireEvent.keyDown(screen.getByRole("button", { name: "Tilldela talare" }), {
    key: "Enter"
  });
  await press(await screen.findByRole("menuitem", { name: speaker }));
};
const raw: TranscriptSegment[] = [
  {
    index: 0,
    fileIndex: 0,
    start: 3,
    end: 8,
    speaker: "SPEAKER_00",
    speakerAttribution: "provisional",
    text: "Hej där."
  },
  {
    index: 1,
    fileIndex: 0,
    start: 8,
    end: 12,
    speaker: "SPEAKER_01",
    speakerAttribution: "provisional",
    text: "Ja tack."
  }
];
afterEach(() => {
  cleanup();
  window.getSelection()?.removeAllRanges();
});
function rangeIn(el: Element, start: number, end = start) {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  const node = walker.nextNode()!;
  const range = document.createRange();
  range.setStart(node, start);
  range.setEnd(node, end);
  window.getSelection()?.removeAllRanges();
  window.getSelection()?.addRange(range);
  return range;
}
it("selects the complete dotted passage, confirms without advancing, and undoes once", async () => {
  const onSave = vi.fn();
  const { container } = render(Fixture, { segments: raw, onSave });
  await fireEvent.click(screen.getByRole("button", { name: /Markera hela passagen: Hej/ }));
  await fireEvent.click(screen.getByRole("button", { name: "Bekräfta Anna" }));
  expect(onSave.mock.calls[0][0].speakerEdits[0]).toMatchObject({
    original: null,
    char_start: null,
    char_end: null,
    decision: "confirmed"
  });
  expect(
    (screen.getByRole("button", { name: "Bekräftad: Anna" }) as HTMLButtonElement).disabled
  ).toBe(true);
  expect(container.querySelectorAll("[data-turn-index]")).toHaveLength(2);
  await fireEvent.click(screen.getByRole("button", { name: "Ångra" }));
  expect(onSave.mock.calls.at(-1)![0].speakerEdits).toEqual([]);
});
it("preserves native cross-source selection and saves both sources in one action", async () => {
  const onSave = vi.fn();
  const { container } = render(Fixture, { segments: raw, onSave });
  const spans = container.querySelectorAll("[data-text-span]");
  const first = document.createTreeWalker(spans[0], NodeFilter.SHOW_TEXT).nextNode()!;
  const last = document.createTreeWalker(spans[1], NodeFilter.SHOW_TEXT).nextNode()!;
  const range = document.createRange();
  range.setStart(first, 4);
  range.setEnd(last, 2);
  window.getSelection()?.addRange(range);
  await fireEvent(document, new Event("selectionchange"));
  await assignTo("Bo");
  expect(onSave).toHaveBeenCalledTimes(1);
  expect(
    onSave.mock.calls[0][0].speakerEdits.map((e: { segment_index: number }) => e.segment_index)
  ).toEqual([0, 1]);
});
it("bulk confirms mixed suggestions in one save with one undo", async () => {
  const onSave = vi.fn();
  render(Fixture, { segments: raw, onSave });
  await fireEvent.click(screen.getByRole("button", { name: "Bekräfta alla förslag (2)" }));
  expect(onSave).toHaveBeenCalledTimes(1);
  expect(onSave.mock.calls[0][0].speakerEdits.map((e: { speaker: string }) => e.speaker)).toEqual([
    "SPEAKER_00",
    "SPEAKER_01"
  ]);
  await fireEvent.click(screen.getByRole("button", { name: "Ångra" }));
  expect(onSave.mock.calls[1][0].speakerEdits).toEqual([]);
});
it("allows unresolved without audio while affirmative confirmation stays disabled", async () => {
  const onSave = vi.fn();
  render(Fixture, { segments: raw, onSave, audioAvailable: false });
  await fireEvent.click(screen.getByRole("button", { name: /Markera hela passagen: Hej/ }));
  expect(
    (screen.getByRole("button", { name: "Bekräfta Anna" }) as HTMLButtonElement).disabled
  ).toBe(true);
  await assignTo("Går inte att avgöra");
  expect(onSave.mock.calls[0][0].speakerEdits[0].decision).toBe("unresolved");
});
it("typing at a caret preserves punctuation and restores the caret after each update", async () => {
  const onSave = vi.fn();
  const { container } = render(Fixture, { segments: raw, onSave });
  const textbox = screen.getByRole("textbox", { name: /Transkript,/ });
  const span = container.querySelector("[data-text-span]")!;
  rangeIn(span, 3);
  await fireEvent(
    textbox,
    new InputEvent("beforeinput", {
      inputType: "insertText",
      data: ".",
      bubbles: true,
      cancelable: true
    })
  );
  await waitFor(() =>
    expect(container.querySelector("[data-text-span]")!.textContent).toBe("Hej. där.")
  );
  expect(window.getSelection()!.anchorOffset).toBe(4);
  await fireEvent(
    textbox,
    new InputEvent("beforeinput", {
      inputType: "insertText",
      data: "!",
      bubbles: true,
      cancelable: true
    })
  );
  await waitFor(() =>
    expect(container.querySelector("[data-text-span]")!.textContent).toBe("Hej.! där.")
  );
  await fireEvent(
    textbox,
    new InputEvent("beforeinput", {
      inputType: "deleteContentBackward",
      bubbles: true,
      cancelable: true
    })
  );
  await waitFor(() =>
    expect(container.querySelector("[data-text-span]")!.textContent).toBe("Hej. där.")
  );
  await fireEvent.keyDown(textbox, { key: "z", ctrlKey: true });
  expect(container.querySelector("[data-text-span]")!.textContent).toBe("Hej.! där.");
});
it("word-click seeking preserves playback, and explicit Listen starts context replay", async () => {
  const onSeek = vi.fn();
  render(Fixture, {
    segments: [{ ...raw[0], speakerAttribution: "assigned" }],
    onSeek,
    playing: false
  });
  await fireEvent.click(screen.getByRole("button", { name: /Flytta uppspelningen till: Hej/ }));
  expect(onSeek).toHaveBeenLastCalledWith(0, 3, false);
  await fireEvent.click(screen.getByRole("button", { name: "Anna" }));
  await fireEvent.click(screen.getByRole("button", { name: "Lyssna" }));
  expect(onSeek).toHaveBeenLastCalledWith(0, 1.5, true, 9);
});
it("prevents text writes when read-only", async () => {
  const onSave = vi.fn();
  const { container } = render(Fixture, { segments: raw, onSave, editable: false });
  rangeIn(container.querySelector("[data-text-span]")!, 3);
  await fireEvent(
    screen.getByRole("textbox"),
    new InputEvent("beforeinput", {
      inputType: "insertText",
      data: "!",
      bubbles: true,
      cancelable: true
    })
  );
  expect(onSave).not.toHaveBeenCalled();
});

it("wordless overlaps remain navigable evidence without an assignable text range", async () => {
  const onSeek = vi.fn();
  render(Fixture, {
    segments: [],
    onSeek,
    speakerReviews: [
      {
        fileIndex: 0,
        overlapDetection: "available",
        detailsOmitted: false,
        overlaps: [{ id: "file:overlap", start: 5, end: 7, detected_speaker_count: 2 }]
      }
    ]
  });
  expect(screen.getByText("1 ställen att granska")).toBeTruthy();
  await fireEvent.click(screen.getByRole("button", { name: "Nästa" }));
  expect(screen.getByText(/Inga transkriptord finns/)).toBeTruthy();
  expect(screen.queryByLabelText("Tilldela talare")).toBeNull();
  await fireEvent.click(screen.getByRole("button", { name: "Lyssna på intervallet" }));
  expect(onSeek).toHaveBeenCalledWith(0, 3.5, true, 8);
});

it("preserves exact sentence spacing across review fragments and joins sources with one space", async () => {
  const segments = [
    { ...raw[0], text: "Hej  där. Nästa mening." },
    { ...raw[1], speaker: "SPEAKER_00", text: "Fortsätt här." }
  ];
  const { container } = render(Fixture, { segments });
  const paragraph = container.querySelector('[data-turn-index="0"] > p')!;
  const expected = segments.map((s) => s.text).join(" ");
  expect(paragraph.textContent).toBe(expected);
  rangeIn(container.querySelector("[data-text-span]")!, 5, 8);
  await fireEvent(document, new Event("selectionchange"));
  await assignTo("Anna");
  expect(paragraph.querySelectorAll("[data-text-span]")).toHaveLength(4);
  expect(paragraph.textContent).toBe(expected);
});

it.each([" ", "\n"])("shows the returning speaker after an invisible %j fragment", (separator) => {
  const segments: TranscriptSegment[] = [
    { ...raw[0], speakerAttribution: "assigned", text: "Nu måste vi prata allvar." + separator },
    {
      ...raw[1],
      speaker: "SPEAKER_00",
      speakerAttribution: "assigned",
      text: "Du måste kunna läsa denna."
    },
    {
      ...raw[1],
      index: 2,
      start: 12,
      end: 16,
      speaker: "SPEAKER_00",
      speakerAttribution: "assigned",
      text: "Jag har läst den flera gånger."
    }
  ];
  const draft = assignSelection(
    { occurrences: [], speakerEdits: [] },
    segments,
    [
      { segmentIndex: 0, start: 0, end: segments[0].text.trimEnd().length },
      { segmentIndex: 2, start: 0, end: segments[2].text.length }
    ],
    "SPEAKER_01"
  );
  const { container } = render(Editor, {
    segments,
    draft,
    audioAvailable: true,
    currentFile: 0,
    currentTime: 0,
    playing: false,
    displayName: (speaker: string) => (speaker === "SPEAKER_00" ? "Annie" : "Stefan"),
    speakerOptions: ["SPEAKER_00", "SPEAKER_01"],
    onSeek: vi.fn(),
    onInteract: vi.fn()
  });
  const phrase = container.querySelector('[data-segment-index="1"]')!;
  expect(phrase.textContent).toBe("Du måste kunna läsa denna.");
  expect(phrase.previousElementSibling?.textContent).toBe("Annie");
  expect(
    container.querySelector('[data-segment-index="2"]')?.previousElementSibling?.textContent
  ).toBe("Stefan");
});
