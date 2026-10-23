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
it("asks before quoting on a narrow screen takes unsaved edits away", async () => {
  const preview = panel();
  preview.besideConversation = false;
  const document = { ...file, name: "report.md", mimetype: "text/markdown" };
  preview.open(document);
  await vi.waitFor(() => expect(preview.status).toBe("ready"));
  preview.setEdits(document.id, "# Edited\n");
  preview.quoteSelection("Budget: 10", null);
  expect(preview.quote?.fileId).toBe(document.id);
  expect(preview.shown).toBe(true);
  expect(preview.pendingDiscard).not.toBeNull();
  preview.keepEditing();
  expect(preview.editsOf(document)).toBe("# Edited\n");
});
it("keeps the edited text for an editor that shows the document afresh", async () => {
  const preview = panel();
  const document = { ...file, name: "report.md", mimetype: "text/markdown" };
  vi.mocked(loadPreview).mockResolvedValue({ kind: "markdown", text: "# Draft", truncated: false });
  preview.open(document);
  await vi.waitFor(() => expect(preview.status).toBe("ready"));
  preview.setEdits(document.id, "# Edited\n");
  expect(preview.editsOf(document)).toBe("# Edited\n");
  expect(preview.editsOf({ id: "other" })).toBeNull();
  // Undone back to the file's text: nothing is unsaved.
  preview.setEdits(document.id, null);
  expect(preview.dirty).toBe(false);
  expect(preview.editsOf(document)).toBeNull();
  preview.setEdits(document.id, "# Edited again\n");
  preview.dropEdits();
  expect(preview.editsOf(document)).toBeNull();
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

it("opens the overview over a file and remembers what opened it", () => {
  const preview = panel();
  const opener = { id: "" } as HTMLElement;
  preview.open(file);
  preview.showOverview("uploads", opener, "question-2");
  expect(preview.shown).toBe(false);
  expect(opener.id).not.toBe("");
  expect(preview.overview).toEqual({ section: "uploads", group: "question-2", opener: opener.id });
  expect(preview.isOverviewOpener(opener)).toBe(true);
  expect(preview.isOverviewOpener({ id: "other" } as HTMLElement)).toBe(false);
  preview.closeOverview();
  expect(preview.overviewShown).toBe(false);
  expect(preview.isOverviewOpener(opener)).toBe(false);
});

it("opens the overview without a section from the panel's own controls", () => {
  const preview = panel();
  preview.showOverview();
  expect(preview.overview).toEqual({ section: null, group: null, opener: null });
  preview.closeOverview(false);
  expect(preview.overview).toBeNull();
});

it("shows a saved version at once and keeps it ready for the next opening", async () => {
  const preview = panel();
  const document = { ...file, name: "report.md", mimetype: "text/markdown" };
  vi.mocked(loadPreview).mockResolvedValue({ kind: "markdown", text: "# Draft", truncated: false });
  preview.open(document);
  await vi.waitFor(() => expect(preview.status).toBe("ready"));
  preview.setEdits(document.id, "# Edited\n");
  expect(preview.unsaved).toBe(true);

  const version = { ...document, id: "report-2" };
  preview.saved(version, "# Final\n");

  expect(preview.dirty).toBe(false);
  expect(preview.file).toEqual(version);
  expect(preview.content).toEqual({ kind: "markdown", text: "# Final\n", truncated: false });
  vi.mocked(loadPreview).mockClear();
  preview.open(file);
  preview.open(version);
  await vi.waitFor(() => expect(preview.file).toEqual(version));
  expect(loadPreview).not.toHaveBeenCalledWith(
    version,
    expect.anything(),
    expect.anything(),
    expect.anything()
  );
});

it("asks before unsaved edits are lost and then does what was asked", async () => {
  const preview = panel();
  const document = { ...file, name: "report.md", mimetype: "text/markdown" };
  vi.mocked(loadPreview).mockResolvedValue({ kind: "markdown", text: "# Draft", truncated: false });
  preview.open(document);
  await vi.waitFor(() => expect(preview.status).toBe("ready"));
  preview.setEdits(document.id, "# Edited\n");

  preview.close();
  expect(preview.shown).toBe(true);
  expect(preview.pendingDiscard).not.toBeNull();
  preview.keepEditing();
  expect(preview.pendingDiscard).toBeNull();
  expect(preview.dirty).toBe(true);

  preview.close();
  preview.pendingDiscard?.proceed();
  expect(preview.shown).toBe(false);
  expect(preview.dirty).toBe(false);
});

it("holds a newer version back while edits are unsaved and shows it when they are dropped", async () => {
  const preview = panel();
  const document = { ...file, name: "report.md", mimetype: "text/markdown" };
  vi.mocked(loadPreview).mockResolvedValue({ kind: "markdown", text: "# Draft", truncated: false });
  preview.open(document);
  await vi.waitFor(() => expect(preview.status).toBe("ready"));
  preview.setEdits(document.id, "# Edited\n");

  const newer = { ...document, id: "report-2" };
  preview.arrive(newer);
  await vi.waitFor(() => expect(preview.replacementContent).not.toBeNull());
  preview.finishReplacement(newer.id);
  expect(preview.file).toEqual(document);

  preview.dropEdits();
  expect(preview.file).toEqual(newer);
  expect(preview.dirty).toBe(false);
});

it("shows the finished document, not the draft it was, when edits are let go after the draft was asked for", async () => {
  const preview = panel();
  const document = { ...file, name: "report.md", mimetype: "text/markdown" };
  vi.mocked(loadPreview).mockResolvedValue({ kind: "markdown", text: "# Draft", truncated: false });
  preview.open(document);
  await vi.waitFor(() => expect(preview.status).toBe("ready"));
  preview.setEdits(document.id, "# Edited\n");

  preview.showDraft(draft);
  expect(preview.pendingDiscard).not.toBeNull();
  const finished = { ...document, id: "report-2" };
  preview.arrive(finished, null, draft.callId);
  await vi.waitFor(() => expect(preview.replacementContent).not.toBeNull());
  preview.finishReplacement(finished.id);
  expect(preview.file).toEqual(document);

  preview.pendingDiscard?.proceed();
  await vi.waitFor(() => expect(preview.status).toBe("ready"));
  expect(preview.file).toEqual(finished);
  expect(preview.draft).toBeNull();
  expect(preview.dirty).toBe(false);
});

it("shows the draft as it stands when edits are let go, not as it was when asked for", async () => {
  const preview = panel();
  const document = { ...file, name: "report.md", mimetype: "text/markdown" };
  vi.mocked(loadPreview).mockResolvedValue({ kind: "markdown", text: "# Draft", truncated: false });
  preview.open(document);
  await vi.waitFor(() => expect(preview.status).toBe("ready"));
  preview.setEdits(document.id, "# Edited\n");

  preview.showDraft(draft);
  preview.write({ ...draft, text: "Introduction and more" });
  expect(preview.file).toEqual(document);

  preview.pendingDiscard?.proceed();
  expect(preview.file).toBeNull();
  expect(preview.draft?.text).toBe("Introduction and more");
});

it("a save in flight no longer applies once a draft takes the panel", async () => {
  const preview = panel();
  const document = { ...file, name: "report.md", mimetype: "text/markdown" };
  vi.mocked(loadPreview).mockResolvedValue({ kind: "markdown", text: "# Draft", truncated: false });
  preview.open(document);
  await vi.waitFor(() => expect(preview.status).toBe("ready"));
  const request = preview.beginSave();
  expect(preview.saving).toBe(true);

  preview.showDraft(draft);
  expect(preview.saving).toBe(false);
  expect(request.apply({ ...document, id: "report-2" }, "# Restored\n")).toBe(false);
  expect(preview.file).toBeNull();
  expect(preview.draft).toEqual(draft);
});

it("a save settles a question about discarding edits that was still open", async () => {
  const preview = panel();
  const document = { ...file, name: "report.md", mimetype: "text/markdown" };
  vi.mocked(loadPreview).mockResolvedValue({ kind: "markdown", text: "# Draft", truncated: false });
  preview.open(document);
  await vi.waitFor(() => expect(preview.status).toBe("ready"));
  preview.setEdits(document.id, "# Edited\n");
  // Something asked to close while the save was in flight.
  preview.close();
  expect(preview.pendingDiscard).not.toBeNull();

  preview.saved({ ...document, id: "report-2" }, "# Final\n");

  expect(preview.pendingDiscard).toBeNull();
  expect(preview.shown).toBe(true);
});

it("shows a ready replacement when edits are undone to the saved text", async () => {
  const preview = await existingPanel();
  preview.setEdits(file.id, "Edited text");
  preview.arrive(revision);
  await vi.waitFor(() => expect(preview.replacementContent).not.toBeNull());
  preview.finishReplacement(revision.id);
  expect(preview.file).toEqual(file);

  preview.setEdits(file.id, null);

  expect(preview.file).toEqual(revision);
  expect(preview.replacementFile).toBeNull();
  expect(preview.editsOf(file)).toBeNull();
  expect(preview.dirty).toBe(false);
});

it("waits for the replacement renderer if edits are undone before it is ready", async () => {
  const preview = await existingPanel();
  preview.setEdits(file.id, "Edited text");
  preview.arrive(revision);
  await vi.waitFor(() => expect(preview.replacementContent).not.toBeNull());

  preview.setEdits(file.id, null);
  expect(preview.file).toEqual(file);

  preview.finishReplacement(revision.id);
  expect(preview.file).toEqual(revision);
});

it("an older save cannot apply to a reopened file or clear a newer save", async () => {
  const preview = await existingPanel();
  const first = preview.beginSave();
  expect(preview.saving).toBe(true);
  preview.close();
  expect(preview.saving).toBe(false);
  preview.open(file);
  const second = preview.beginSave();

  expect(first.apply(revision, "Old save")).toBe(false);
  first.finish();
  expect(preview.saving).toBe(true);
  expect(preview.file).toEqual(file);

  expect(second.apply(revision, "Current save")).toBe(true);
  second.finish();
  expect(preview.file).toEqual(revision);
  expect(preview.saving).toBe(false);
});

it("shows the document being written again when the reader asks, after closing it", () => {
  const preview = panel();
  preview.besideConversation = true;
  preview.write(draft);
  expect(preview.draft?.callId).toBe("one");
  preview.close();
  preview.write({ ...draft, text: "More" });
  expect(preview.shown).toBe(false);

  preview.showDraft({ ...draft, text: "More" });

  expect(preview.draft?.text).toBe("More");
  // The rest of the document follows into the panel again.
  preview.write({ ...draft, text: "More still" });
  expect(preview.draft?.text).toBe("More still");
});

it("shows the document being written on a narrow screen when the reader asks", () => {
  const preview = panel();
  preview.besideConversation = false;
  preview.write(draft);
  expect(preview.shown).toBe(false);

  preview.showDraft(draft);

  expect(preview.shown).toBe(true);
  expect(preview.draft?.callId).toBe("one");
});
