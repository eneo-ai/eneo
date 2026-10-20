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

it("folds the conversation away and back, apart from a closing file's reset of the maximised panel", async () => {
  const store = panel();
  store.openNative("flow");
  store.setConversationCollapsed(true);
  expect(store.conversationCollapsed).toBe(true);

  store.open(file);
  await vi.waitFor(() => expect(store.status).toBe("ready"));
  store.close();
  expect(store.maximised).toBe(false);
  expect(store.conversationCollapsed).toBe(true);

  store.setConversationCollapsed(false);
  expect(store.conversationCollapsed).toBe(false);
});

it("shows native content until a file covers it, and again when the file closes", async () => {
  const store = panel();
  store.openNative("flow");
  expect(store.occupant).toEqual({ kind: "native", id: "flow" });
  expect(store.active).toBe(true);

  store.open(file);
  expect(store.occupant).toEqual({ kind: "file" });
  await vi.waitFor(() => expect(store.status).toBe("ready"));
  store.close();
  expect(store.occupant).toEqual({ kind: "native", id: "flow" });

  store.closeNative();
  expect(store.occupant).toEqual({ kind: "closed" });
});

it("lets a document the assistant writes take the panel over native content", () => {
  const store = panel();
  store.openNative("flow");
  store.write(draft);
  expect(store.occupant).toEqual({ kind: "file" });
  expect(store.openedByItself).toBe(true);
  store.endDraft();
  expect(store.occupant).toEqual({ kind: "native", id: "flow" });
});

it("replaces the overview with native content and closes it with everything else", () => {
  const store = panel();
  store.showOverview();
  store.openNative("flow");
  expect(store.overview).toBeNull();
  expect(store.occupant).toEqual({ kind: "native", id: "flow" });
  store.closeAll();
  expect(store.nativeId).toBeNull();
  expect(store.occupant).toEqual({ kind: "closed" });
});
