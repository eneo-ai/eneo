import { beforeEach, expect, it, vi } from "vitest";
import { FilePreview } from "./FilePreview.svelte";
import { loadPreview } from "./loadPreview";
vi.mock("./loadPreview", () => ({
  loadPreview: vi.fn(),
  PreviewTooLargeError: class extends Error {}
}));
const draft = { callId: "one", title: "Report", text: "Introduction" };
const file = {
  id: "report",
  name: "report.docx",
  mimetype: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  size: 100
};
function panel() {
  const preview = new FilePreview({
    resolveOriginalUrl: vi.fn().mockResolvedValue("/file")
  } as never);
  preview.besideConversation = true;
  return preview;
}
beforeEach(() => {
  vi.mocked(loadPreview).mockResolvedValue({ kind: "text", text: "Ready", truncated: false });
});
it("opens at creation start and hands off to the saved file", async () => {
  const preview = panel();
  preview.write(draft);
  expect(preview.shown).toBe(true);
  expect(preview.openedByItself).toBe(true);
  preview.arrive(file);
  await vi.waitFor(() => expect(preview.status).toBe("ready"));
  expect(preview.draft).toBeNull();
  expect(preview.file).toEqual(file);
});
it("honors closing the draft until the next answer", () => {
  const preview = panel();
  preview.write(draft);
  preview.close();
  preview.write({ ...draft, text: "More" });
  preview.arrive(file);
  expect(preview.shown).toBe(false);
  preview.beginAnswer();
  preview.write({ ...draft, callId: "two" });
  expect(preview.shown).toBe(true);
});
it("does not pop a narrow-screen sheet over the conversation", () => {
  const preview = panel();
  preview.besideConversation = false;
  preview.write(draft);
  expect(preview.shown).toBe(false);
});
it("opens for a completed Word file even when no draft input was streamed", () => {
  const preview = panel();
  preview.arrive(file);
  expect(preview.shown).toBe(true);
});
it("does not let an earlier file load overwrite a new draft", async () => {
  let finish!: (content: Awaited<ReturnType<typeof loadPreview>>) => void;
  vi.mocked(loadPreview).mockReturnValueOnce(
    new Promise((resolve) => {
      finish = resolve;
    })
  );
  const preview = panel();
  preview.open(file);
  await vi.waitFor(() => expect(finish).toBeDefined());
  preview.write(draft);
  finish({ kind: "text", text: "Old file", truncated: false });
  await Promise.resolve();
  expect(preview.draft).toEqual(draft);
  expect(preview.file).toBeNull();
});

it("retains the draft when the answer ends before the saved file finishes loading", async () => {
  let finish!: (content: Awaited<ReturnType<typeof loadPreview>>) => void;
  vi.mocked(loadPreview).mockReturnValueOnce(
    new Promise((resolve) => {
      finish = resolve;
    })
  );
  const preview = panel();
  preview.write(draft);
  preview.arrive(file);
  preview.endDraft();
  expect(preview.draft).toEqual(draft);
  await vi.waitFor(() => expect(finish).toBeDefined());
  finish({ kind: "text", text: "Final", truncated: false });
  await vi.waitFor(() => expect(preview.status).toBe("ready"));
  expect(preview.draft).toBeNull();
  preview.write(draft);
  expect(preview.draft).toBeNull();
  expect(preview.content).toMatchObject({ text: "Final" });
});

it("keeps a labelled previous draft until the retry has actual content", () => {
  const preview = panel();
  preview.write(draft);
  preview.write({ callId: "retry", title: "", text: "" });
  expect(preview.draft).toMatchObject({
    callId: "retry",
    title: "Report",
    text: "Introduction",
    showingPreviousDraft: true
  });
  preview.write({ callId: "retry", title: "Corrected report", text: "" });
  expect(preview.draft).toMatchObject({
    title: "Corrected report",
    text: "Introduction",
    showingPreviousDraft: true
  });
  preview.write({ callId: "retry", title: "Corrected report", text: "Corrected introduction" });
  expect(preview.draft).toMatchObject({ text: "Corrected introduction" });
  expect(preview.draft?.showingPreviousDraft).not.toBe(true);
});

it("discards an unfinished draft when no file arrives", () => {
  const preview = panel();
  preview.write(draft);
  preview.endDraft();
  expect(preview.shown).toBe(false);
});

const revision = { ...file, id: "revision", name: "revised-report.docx" };
const revisedContent = { kind: "text" as const, text: "Revised", truncated: false };
async function existingPanel() {
  const preview = panel();
  preview.open(file);
  await vi.waitFor(() => expect(preview.status).toBe("ready"));
  return preview;
}

it("keeps the current version through writing, download and rendering, then swaps once", async () => {
  const preview = await existingPanel();
  const originalContent = preview.content;
  preview.beginAnswer();
  preview.write({ ...draft, callId: "edit", title: "Revised report" });
  expect(preview.file).toEqual(file);
  expect(preview.content).toBe(originalContent);
  let finish!: (content: Awaited<ReturnType<typeof loadPreview>>) => void;
  vi.mocked(loadPreview).mockReturnValueOnce(
    new Promise((resolve) => {
      finish = resolve;
    })
  );
  preview.arrive(revision);
  preview.endDraft();
  expect(preview.file).toEqual(file);
  expect(preview.status).toBe("ready");
  await vi.waitFor(() => expect(finish).toBeDefined());
  finish(revisedContent);
  await vi.waitFor(() => expect(preview.replacementContent).toEqual(revisedContent));
  expect(preview.content).toBe(originalContent);
  preview.finishReplacement("wrong-id");
  expect(preview.file).toEqual(file);
  preview.finishReplacement(revision.id);
  expect(preview.file).toEqual(revision);
  expect(preview.content).toEqual(revisedContent);
  expect(preview.draft).toBeNull();
  expect(preview.replacementFile).toBeNull();
  preview.write({ ...draft, callId: "edit" });
  expect(preview.draft).toBeNull();
});

it("keeps the current version if generation stops without a file", async () => {
  const preview = await existingPanel();
  preview.write(draft);
  preview.endDraft();
  expect(preview.file).toEqual(file);
  expect(preview.content).toMatchObject({ text: "Ready" });
  expect(preview.draft).toBeNull();
});

it("retains the old document after download or renderer failure and can retry", async () => {
  const preview = await existingPanel();
  vi.mocked(loadPreview).mockRejectedValueOnce(new Error("offline"));
  preview.write(draft);
  preview.arrive(revision);
  await vi.waitFor(() => expect(preview.replacementError).toBe("failed"));
  expect(preview.file).toEqual(file);
  expect(preview.status).toBe("ready");
  expect(preview.draft).toBeNull();
  vi.mocked(loadPreview).mockResolvedValueOnce(revisedContent);
  preview.retry();
  await vi.waitFor(() => expect(preview.replacementContent).toEqual(revisedContent));
  preview.failReplacement(revision.id);
  expect(preview.replacementError).toBe("failed");
  expect(preview.file).toEqual(file);
  preview.retry();
  await vi.waitFor(() => expect(preview.replacementContent).toEqual(revisedContent));
  preview.finishReplacement(revision.id);
  expect(preview.file).toEqual(revision);
});

it.each(["close", "open"] as const)(
  "does not take over after the reader chooses to %s",
  async (action) => {
    const preview = await existingPanel();
    let finish!: (content: Awaited<ReturnType<typeof loadPreview>>) => void;
    vi.mocked(loadPreview).mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      })
    );
    preview.write(draft);
    preview.arrive(revision);
    await vi.waitFor(() => expect(finish).toBeDefined());
    if (action === "close") preview.close();
    else preview.open(file);
    finish(revisedContent);
    await Promise.resolve();
    preview.finishReplacement(revision.id);
    expect(preview.replacementFile).toBeNull();
    expect(preview.file).toEqual(action === "close" ? null : file);
    expect(preview.draft).toBeNull();
  }
);

it("does not replace a file the user selects while the edit is still being generated", async () => {
  const preview = await existingPanel();
  preview.write(draft);
  preview.open(file);
  preview.arrive(revision, null, draft.callId);
  expect(preview.replacementFile).toBeNull();
  expect(preview.file).toEqual(file);
});
it("does not cancel an initial download when its filename is clicked again", async () => {
  let finish!: (content: Awaited<ReturnType<typeof loadPreview>>) => void;
  vi.mocked(loadPreview).mockReturnValueOnce(
    new Promise((resolve) => {
      finish = resolve;
    })
  );
  const preview = panel();
  preview.open(file);
  await vi.waitFor(() => expect(finish).toBeDefined());
  preview.open(file);
  finish(revisedContent);
  await vi.waitFor(() => expect(preview.status).toBe("ready"));
});

it("keeps a quote tied to its original file when the preview changes", async () => {
  const preview = panel();
  preview.open(file);
  await vi.waitFor(() => expect(preview.status).toBe("ready"));
  preview.quoteSelection("Budget: 10", 'sheet "Data", row 2 (data row 1), column B');
  preview.open({ ...file, id: "other", name: "other.xlsx" });
  expect(preview.quote?.fileId).toBe(file.id);
  expect(preview.quote?.text).toBe("Budget: 10");
});
it("quotes what a view says is selected until that view withdraws it", () => {
  const preview = panel();
  preview.quoteView("call-1", "Deviation\nby month", " January\t1965 ");
  expect(preview.quote).toEqual({
    viewCallId: "call-1",
    fileName: "Deviation by month",
    text: "January\t1965",
    locator: null
  });
  // Another view has no say over a quote that is not its own.
  preview.quoteView("call-2", "Other view", "");
  expect(preview.quote?.viewCallId).toBe("call-1");
  preview.quoteView("call-1", "Deviation by month", "");
  expect(preview.quote).toBeNull();
});
it("returns to the composer after quoting on a narrow screen", async () => {
  const preview = panel();
  preview.besideConversation = false;
  preview.open(file);
  await vi.waitFor(() => expect(preview.status).toBe("ready"));
  preview.quoteSelection("Budget: 10", null);
  expect(preview.shown).toBe(false);
  expect(preview.quote?.fileId).toBe(file.id);
});
it("keeps the file beneath a cover and shows it again when the cover goes", async () => {
  const preview = panel();
  preview.open(file);
  await vi.waitFor(() => expect(preview.status).toBe("ready"));
  preview.cover = { leave: () => (preview.cover = null) };
  expect(preview.isOpen(file)).toBe(false);
  preview.cover = null;
  expect(preview.isOpen(file)).toBe(true);
  expect(preview.content).not.toBeNull();
});
it("sends the cover away when the covered file is asked for again", async () => {
  const preview = panel();
  preview.open(file);
  await vi.waitFor(() => expect(preview.status).toBe("ready"));
  preview.cover = { leave: () => (preview.cover = null) };
  preview.toggle(file);
  expect(preview.cover).toBeNull();
  expect(preview.isOpen(file)).toBe(true);
});
