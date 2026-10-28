// @vitest-environment jsdom
import { beforeEach, expect, it, vi } from "vitest";
import { loadPreview } from "@/features/workspace/preview/load-preview";
import { SidePanelStore } from "./side-panel-store";

vi.mock("@/features/workspace/preview/load-preview", () => ({
  loadPreview: vi.fn(),
  PreviewTooLargeError: class extends Error {}
}));

type Content = Awaited<ReturnType<typeof loadPreview>>;

const draft = { callId: "one", title: "Report", text: "Introduction" };
const file = {
  id: "report",
  name: "report.docx",
  mimetype: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  size: 100
};
const revision = { ...file, id: "report-2" };

function panel() {
  const store = new SidePanelStore(() => Promise.resolve("/file"));
  store.setBesideConversation(true);
  return store;
}

function deferred() {
  let finish!: (content: Content) => void;
  vi.mocked(loadPreview).mockReturnValueOnce(
    new Promise((resolve) => {
      finish = resolve;
    })
  );
  return () => finish;
}

beforeEach(() => {
  vi.mocked(loadPreview).mockReset();
  vi.mocked(loadPreview).mockResolvedValue({ kind: "text", text: "Ready", truncated: false });
});

it("opens at creation start and hands off to the saved file", async () => {
  const store = panel();
  store.write(draft);
  expect(store.occupant).toEqual({ kind: "file" });
  expect(store.openedByItself).toBe(true);
  store.arrive(file);
  await vi.waitFor(() => expect(store.status).toBe("ready"));
  expect(store.draft).toBeNull();
  expect(store.file).toEqual(file);
});

it("honours closing the draft until the next answer", () => {
  const store = panel();
  store.write(draft);
  store.close();
  store.write({ ...draft, text: "More" });
  store.arrive(file);
  expect(store.shown).toBe(false);
  store.beginAnswer();
  store.write({ ...draft, callId: "two" });
  expect(store.shown).toBe(true);
});

it("does not pop a narrow-screen sheet over the conversation", () => {
  const store = panel();
  store.setBesideConversation(false);
  store.write(draft);
  expect(store.shown).toBe(false);
});

it("opens for a completed file even when no draft input was streamed", () => {
  const store = panel();
  store.arrive(file);
  expect(store.shown).toBe(true);
});

it("does not let an earlier file load overwrite a new draft", async () => {
  const finish = deferred();
  const store = panel();
  store.open(file);
  await vi.waitFor(() => expect(finish()).toBeDefined());
  store.write(draft);
  finish()({ kind: "text", text: "Old file", truncated: false });
  await Promise.resolve();
  expect(store.draft).toEqual(draft);
  expect(store.file).toBeNull();
});

it("keeps the current version through writing, download and rendering, then swaps once", async () => {
  const store = panel();
  store.open(file);
  await vi.waitFor(() => expect(store.status).toBe("ready"));
  const finish = deferred();
  store.write({ ...draft, callId: "edit" });
  expect(store.file).toEqual(file);
  expect(store.draft?.callId).toBe("edit");
  store.arrive(revision, { text: "changed", locator: null }, "edit");
  expect(store.file).toEqual(file);
  expect(store.replacementFile).toEqual(revision);
  await vi.waitFor(() => expect(finish()).toBeDefined());
  finish()({ kind: "text", text: "New", truncated: false });
  await vi.waitFor(() => expect(store.replacementContent).not.toBeNull());
  // The renderer says when it is ready; only then does the panel swap.
  expect(store.file).toEqual(file);
  store.finishReplacement(revision.id);
  expect(store.file).toEqual(revision);
  expect(store.highlight).toEqual({ text: "changed", locator: null });
  expect(store.draft).toBeNull();
});

it("retains the old document after a renderer failure and can retry", async () => {
  const store = panel();
  store.open(file);
  await vi.waitFor(() => expect(store.status).toBe("ready"));
  store.arrive(revision);
  await vi.waitFor(() => expect(store.replacementContent).not.toBeNull());
  store.failReplacement(revision.id);
  expect(store.file).toEqual(file);
  expect(store.replacementError).toBe("failed");
  store.retry();
  await vi.waitFor(() => expect(store.replacementContent).not.toBeNull());
});

it("does not cancel an initial download when its file is opened again", async () => {
  const finish = deferred();
  const store = panel();
  store.open(file);
  store.open(file);
  await vi.waitFor(() => expect(finish()).toBeDefined());
  finish()({ kind: "text", text: "Loaded", truncated: false });
  await vi.waitFor(() => expect(store.status).toBe("ready"));
  expect(loadPreview).toHaveBeenCalledTimes(1);
});

it("keeps a quote tied to its original file when the preview changes", async () => {
  const store = panel();
  store.open(file);
  await vi.waitFor(() => expect(store.status).toBe("ready"));
  store.quoteSelection("  A passage  \n\n\n\nmore ", "occurrence 1 of 2");
  expect(store.quote).toEqual({
    fileId: file.id,
    fileName: file.name,
    text: "A passage\n\nmore",
    locator: "occurrence 1 of 2"
  });
  store.open(revision);
  expect(store.quote?.fileId).toBe(file.id);
});

it("quotes what a view says is selected until that view withdraws it", () => {
  const store = panel();
  store.quoteView("call-1", "Budget  2026", "Row 3");
  expect(store.quote).toEqual({
    viewCallId: "call-1",
    fileName: "Budget 2026",
    text: "Row 3",
    locator: null
  });
  store.quoteView("call-2", "Other", "");
  expect(store.quote?.viewCallId).toBe("call-1");
  store.quoteView("call-1", "Budget 2026", "");
  expect(store.quote).toBeNull();
});

it("returns to the composer after quoting on a narrow screen", async () => {
  const store = panel();
  store.setBesideConversation(false);
  store.open(file);
  await vi.waitFor(() => expect(store.status).toBe("ready"));
  store.quoteSelection("Passage", null);
  expect(store.shown).toBe(false);
  expect(store.quote?.text).toBe("Passage");
});

it("keeps the file beneath a view and shows it again when the view goes", async () => {
  const store = panel();
  store.open(file);
  await vi.waitFor(() => expect(store.status).toBe("ready"));
  store.openView("call-1");
  expect(store.occupant).toEqual({ kind: "view", callId: "call-1" });
  expect(store.isOpen(file)).toBe(false);
  store.closeView();
  expect(store.occupant).toEqual({ kind: "file" });
  expect(store.isOpen(file)).toBe(true);
});

it("sends the view away when the covered file is asked for again", async () => {
  const store = panel();
  store.open(file);
  await vi.waitFor(() => expect(store.status).toBe("ready"));
  store.openView("call-1");
  store.open(file);
  expect(store.viewCallId).toBeNull();
  expect(store.file).toEqual(file);
});

it("lets a view of a new answer take the panel again after the reader closed it", () => {
  const store = panel();
  store.openView("call-1");
  store.dismissView();
  expect(store.viewDismissedThisAnswer).toBe(true);
  expect(store.occupant).toEqual({ kind: "closed" });
  store.beginAnswer();
  expect(store.viewDismissedThisAnswer).toBe(false);
});

it("opens the overview over a file and remembers what opened it", async () => {
  const store = panel();
  store.open(file);
  await vi.waitFor(() => expect(store.status).toBe("ready"));
  const opener = document.createElement("button");
  document.body.append(opener);
  store.showOverview("uploads", opener);
  expect(store.occupant).toEqual({ kind: "overview", section: "uploads" });
  expect(store.file).toBeNull();
  store.closeOverview();
  expect(store.occupant).toEqual({ kind: "closed" });
  expect(document.activeElement).toBe(opener);
  opener.remove();
});

it("gives the focus back to its opener once a modal sheet over it has gone", async () => {
  const store = panel();
  const opener = document.createElement("button");
  const sheet = document.createElement("button");
  document.body.append(opener, sheet);
  sheet.focus();
  // A modal sheet still open keeps the opener inert: focusing it does nothing.
  const focus = vi.spyOn(opener, "focus").mockImplementationOnce(() => {});
  store.showOverview("uploads", opener);
  store.closeOverview();
  expect(document.activeElement).toBe(sheet);
  // The sheet goes, and the focus with it.
  sheet.remove();
  await vi.waitFor(() => expect(document.activeElement).toBe(opener));
  expect(focus).toHaveBeenCalledTimes(2);
  opener.remove();
});

it("leaves the focus with the panel's next occupant that took it meanwhile", async () => {
  const store = panel();
  const opener = document.createElement("button");
  const sheet = document.createElement("button");
  const next = document.createElement("button");
  document.body.append(opener, sheet, next);
  sheet.focus();
  vi.spyOn(opener, "focus").mockImplementationOnce(() => {});
  store.showOverview("uploads", opener);
  // Closed to show something else, which takes the focus itself.
  store.closeOverview();
  next.focus();
  await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
  await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
  expect(document.activeElement).toBe(next);
  for (const element of [opener, sheet, next]) element.remove();
});

it("notifies its subscribers once per change", () => {
  const store = panel();
  const listener = vi.fn();
  store.subscribe(listener);
  const before = store.getVersion();
  store.setMaximised(true);
  store.setMaximised(true);
  expect(listener).toHaveBeenCalledTimes(1);
  expect(store.getVersion()).toBe(before + 1);
});

it("keeps a replacement waiting while the reader edits, and shows it once the edits are dropped", async () => {
  const store = panel();
  store.open(file);
  await vi.waitFor(() => expect(store.status).toBe("ready"));
  store.setEdits(file.id, "# Edited\n");
  expect(store.dirty).toBe(true);
  store.arrive(revision);
  await vi.waitFor(() => expect(store.replacementContent).not.toBeNull());
  store.finishReplacement(revision.id);
  expect(store.file).toEqual(file);
  store.dropEdits();
  expect(store.dirty).toBe(false);
  expect(store.file).toEqual(revision);
});

it("asks before edits are lost, and goes on once the reader agrees", async () => {
  const store = panel();
  store.open(file);
  await vi.waitFor(() => expect(store.status).toBe("ready"));
  store.setEdits(file.id, "# Edited\n");
  store.open(revision);
  expect(store.pendingDiscard).not.toBeNull();
  expect(store.file).toEqual(file);
  store.keepEditing();
  expect(store.pendingDiscard).toBeNull();
  expect(store.dirty).toBe(true);
  store.close();
  store.pendingDiscard!.proceed();
  expect(store.dirty).toBe(false);
  expect(store.shown).toBe(false);
});

it("shows the saved version in place of the edited one", async () => {
  const store = panel();
  store.open(file);
  await vi.waitFor(() => expect(store.status).toBe("ready"));
  store.setEdits(file.id, "# Edited\n");
  store.saved(revision, "# Edited\n");
  expect(store.dirty).toBe(false);
  expect(store.file).toEqual(revision);
  expect(store.content).toEqual({ kind: "markdown", text: "# Edited\n", truncated: false });
  // The text is kept for comparing versions without another download.
  await expect(store.loadText(revision)).resolves.toBe("# Edited\n");
});

it("a save settles a question about discarding edits that was still open", async () => {
  const store = panel();
  store.open(file);
  await vi.waitFor(() => expect(store.status).toBe("ready"));
  store.setEdits(file.id, "# Edited\n");
  // Something asked to close while the save was in flight.
  store.close();
  expect(store.pendingDiscard).not.toBeNull();

  store.saved(revision, "# Final\n");

  expect(store.pendingDiscard).toBeNull();
  expect(store.shown).toBe(true);
});

it("asks before quoting on a narrow screen takes unsaved edits away", async () => {
  const store = panel();
  store.setBesideConversation(false);
  store.open(file);
  await vi.waitFor(() => expect(store.status).toBe("ready"));
  store.setEdits(file.id, "# Edited\n");
  store.quoteSelection("Budget: 10", null);
  expect(store.quote?.fileId).toBe(file.id);
  expect(store.shown).toBe(true);
  expect(store.pendingDiscard).not.toBeNull();
  store.keepEditing();
  expect(store.editsOf(file)).toBe("# Edited\n");
});

it("keeps the edited text for an editor that shows the document afresh", async () => {
  const store = panel();
  store.open(file);
  await vi.waitFor(() => expect(store.status).toBe("ready"));
  store.setEdits(file.id, "# Edited\n");
  expect(store.editsOf(file)).toBe("# Edited\n");
  expect(store.editsOf({ id: "other" })).toBeNull();
  // Undone back to the file's text: nothing is unsaved.
  store.setEdits(file.id, null);
  expect(store.dirty).toBe(false);
  expect(store.editsOf(file)).toBeNull();
  store.setEdits(file.id, "# Edited again\n");
  store.dropEdits();
  expect(store.editsOf(file)).toBeNull();
});

const markdownFile = { ...file, name: "report.md", mimetype: "text/markdown" };

async function openDocument() {
  const store = panel();
  vi.mocked(loadPreview).mockResolvedValue({ kind: "markdown", text: "# Draft", truncated: false });
  store.open(markdownFile);
  await vi.waitFor(() => expect(store.status).toBe("ready"));
  return store;
}

it("shows the finished document, not the draft it was, when edits are let go after the draft was asked for", async () => {
  const store = await openDocument();
  store.setEdits(markdownFile.id, "# Edited\n");

  store.showDraft(draft);
  expect(store.pendingDiscard).not.toBeNull();
  const finished = { ...markdownFile, id: "report-2" };
  store.arrive(finished, null, draft.callId);
  await vi.waitFor(() => expect(store.replacementContent).not.toBeNull());
  store.finishReplacement(finished.id);
  expect(store.file).toEqual(markdownFile);

  store.pendingDiscard?.proceed();
  await vi.waitFor(() => expect(store.status).toBe("ready"));
  expect(store.file).toEqual(finished);
  expect(store.draft).toBeNull();
  expect(store.dirty).toBe(false);
});

it("shows the draft as it stands when edits are let go, not as it was when asked for", async () => {
  const store = await openDocument();
  store.setEdits(markdownFile.id, "# Edited\n");

  store.showDraft(draft);
  store.write({ ...draft, text: "Introduction and more" });
  expect(store.file).toEqual(markdownFile);

  store.pendingDiscard?.proceed();
  expect(store.file).toBeNull();
  expect(store.draft?.text).toBe("Introduction and more");
});

it("a save in flight no longer applies once a draft takes the panel", async () => {
  const store = await openDocument();
  const request = store.beginSave();
  expect(store.saving).toBe(true);

  store.showDraft(draft);
  expect(store.saving).toBe(false);
  expect(request.apply({ ...markdownFile, id: "report-2" }, "# Restored\n")).toBe(false);
  expect(store.file).toBeNull();
  expect(store.draft).toEqual(draft);
});

it("shows a ready replacement when edits are undone to the saved text", async () => {
  const store = await openDocument();
  store.setEdits(markdownFile.id, "Edited text");
  const newer = { ...markdownFile, id: "report-2" };
  store.arrive(newer);
  await vi.waitFor(() => expect(store.replacementContent).not.toBeNull());
  store.finishReplacement(newer.id);
  expect(store.file).toEqual(markdownFile);

  store.setEdits(markdownFile.id, null);

  expect(store.file).toEqual(newer);
  expect(store.replacementFile).toBeNull();
  expect(store.editsOf(markdownFile)).toBeNull();
  expect(store.dirty).toBe(false);
});

it("waits for the replacement renderer if edits are undone before it is ready", async () => {
  const store = await openDocument();
  store.setEdits(markdownFile.id, "Edited text");
  const newer = { ...markdownFile, id: "report-2" };
  store.arrive(newer);
  await vi.waitFor(() => expect(store.replacementContent).not.toBeNull());

  store.setEdits(markdownFile.id, null);
  expect(store.file).toEqual(markdownFile);

  store.finishReplacement(newer.id);
  expect(store.file).toEqual(newer);
});

it("an older save cannot apply to a reopened file or clear a newer save", async () => {
  const store = await openDocument();
  const first = store.beginSave();
  expect(store.saving).toBe(true);
  store.close();
  expect(store.saving).toBe(false);
  store.open(markdownFile);
  const second = store.beginSave();

  expect(first.apply(revision, "Old save")).toBe(false);
  first.finish();
  expect(store.saving).toBe(true);
  expect(store.file).toEqual(markdownFile);

  expect(second.apply(revision, "Current save")).toBe(true);
  second.finish();
  expect(store.file).toEqual(revision);
  expect(store.saving).toBe(false);
});

it("shows the document being written again when the reader asks, after closing it", () => {
  const store = panel();
  store.write(draft);
  expect(store.draft?.callId).toBe("one");
  store.close();
  store.write({ ...draft, text: "More" });
  expect(store.shown).toBe(false);

  store.showDraft({ ...draft, text: "More" });

  expect(store.draft?.text).toBe("More");
  // The rest of the document follows into the panel again.
  store.write({ ...draft, text: "More still" });
  expect(store.draft?.text).toBe("More still");
});

it("shows the document being written on a narrow screen when the reader asks", () => {
  const store = panel();
  store.setBesideConversation(false);
  store.write(draft);
  expect(store.shown).toBe(false);

  store.showDraft(draft);

  expect(store.shown).toBe(true);
  expect(store.draft?.callId).toBe("one");
});
