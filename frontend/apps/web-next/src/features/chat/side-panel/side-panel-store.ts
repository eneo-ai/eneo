import {
  loadPreview,
  PreviewTooLargeError,
  type PreviewContent
} from "@/features/workspace/preview/load-preview";
import {
  previewKindOf,
  type PreviewFile,
  type PreviewPassage
} from "@/features/workspace/preview/preview-kind";
import type { DocumentDraft } from "./document-draft";

/** An excerpt the user selected to ask about, in a file or in an interactive view. */
export type PreviewQuote = {
  /** The file the text was selected in; a quote from a view has none. */
  fileId?: string;
  /** The interactive view the text was selected in, by its tool call. */
  viewCallId?: string;
  /** Names where the text is from: the file, or what the view shows. */
  fileName: string;
  text: string;
  /** Which of several identical passages is meant; see `locatePassage`. */
  locator: string | null;
};

export type PreviewStatus = "loading" | "ready" | "too_large" | "failed";

/** What the side region shows; the activity of an answer is shown by the chat view when this is closed. */
export type PanelOccupant =
  | { kind: "view"; callId: string }
  | { kind: "file" }
  | { kind: "overview"; section: "uploads" | null }
  | { kind: "closed" };

// A quote points at a passage; it does not carry the document. A longer
// selection is cut, which still tells the reader where the passage starts.
const QUOTE_MAX_LENGTH = 1500;

function tidyQuoteText(selected: string): string {
  const text = selected
    .replace(/\r\n?/g, "\n")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  return text.length > QUOTE_MAX_LENGTH ? `${text.slice(0, QUOTE_MAX_LENGTH).trimEnd()}…` : text;
}

// Files are immutable, so a prepared preview stays valid; a few are kept so
// flipping between the documents of an answer does not download them again.
const CACHED_PREVIEWS = 4;

/**
 * The state of the side region beside a conversation: the file on show and
 * its loaded content, the document being written, the interactive view
 * covering the file, the overview, the quote waiting for the next question.
 *
 * It is an external store (subscribe + version) so the panel, the message
 * list and the composer read one state, and so the logic is tested without
 * React. Every change bumps the version and notifies the subscribers.
 */
export class SidePanelStore {
  #resolveOriginalUrl: (file: PreviewFile) => Promise<string>;
  #cache = new Map<string, PreviewContent>();
  #abort: AbortController | null = null;
  #opener: HTMLElement | null = null;
  // Whether the panel may open by itself for a document the assistant writes;
  // closing it during an answer withdraws that until the next answer.
  #opensByItself = true;
  // The draft the reader left for another file; it does not take the panel back.
  #leftDraft: string | null = null;
  // The file that has arrived for each of these calls. Late draft effects
  // cannot take over either its download or its completed preview, and a
  // draft the reader asked for after its file came shows that file instead.
  #finishedDrafts = new Map<string, PreviewFile>();
  #replacementHighlight: PreviewPassage | null = null;
  #replacementReady = false;
  #version = 0;
  #listeners = new Set<() => void>();

  file: PreviewFile | null = null;
  /**
   * The document being written. An already loaded file stays visible while
   * its replacement is prepared; otherwise the draft itself is shown.
   */
  draft: DocumentDraft | null = null;
  /**
   * Whether the layout shows the panel beside the conversation. As a sheet
   * over the conversation it never opens by itself.
   */
  besideConversation = false;
  /** Whether the panel was last opened by the assistant's writing, not by the reader. */
  openedByItself = false;
  status: PreviewStatus = "loading";
  content: PreviewContent | null = null;
  /** Stage automatic replacements without tearing down the reader's current view. */
  replacementFile: PreviewFile | null = null;
  replacementContent: PreviewContent | null = null;
  replacementError: "failed" | "too_large" | null = null;
  /**
   * Text selected in a preview and handed to the composer, which sends it with
   * the next question. It outlives the panel: closing the preview keeps it.
   */
  quote: PreviewQuote | null = null;
  /** A passage to point out in the open file: a quote the user asked to see in place. */
  highlight: PreviewPassage | null = null;
  /**
   * A message an interactive view offered on the reader's action in it. The
   * composer takes it as its text; nothing is sent by itself.
   */
  suggestion: string | null = null;
  /**
   * The reader has changed the open document's text. Edits live in the editor
   * until the reader saves them as a new version, so nothing is written on a
   * keystroke; what would lose them asks first.
   */
  dirty = false;
  /** A save is in flight; shared across panel remounts so the document stays read-only. */
  saving = false;
  #saveRequest: symbol | null = null;
  // The edited text itself, so an editor torn down and mounted again (the
  // layout crosses its breakpoint) shows the document as the reader left it.
  #edits: { fileId: string; text: string } | null = null;
  /**
   * Whether the document on show marks what it changed against the version
   * before it. Off until the reader asks: a version that rewrites the
   * document would otherwise open as a strike-through of all its old text.
   */
  showChanges = false;
  /**
   * Something would take the editor away (another file, the panel closing)
   * while edits are unsaved; it waits for the reader to decide.
   */
  pendingDiscard: { proceed: () => void } | null = null;
  /** Whether the panel covers the conversation instead of sharing the width with it. */
  maximised = false;
  /**
   * The interactive tool view shown over the file, by its call. The file
   * stays loaded beneath it and is on show again when the view goes; a file
   * that takes the panel sends the view back to its answer.
   */
  viewCallId: string | null = null;
  /**
   * The user closed the view during the answer being written. A view of
   * that answer may then not take the panel again by itself.
   */
  viewDismissedThisAnswer = false;
  /** Where the shown view's frame is laid out; the frame stays mounted in its message. */
  viewTarget: HTMLElement | null = null;
  /**
   * The calls whose view the reader can bring into the panel: it has loaded,
   * has something to show and can use the room.
   */
  readonly offeredViews = new Set<string>();
  /**
   * The panel's overview of everything the conversation has to show, with the
   * section it opened on and the element to hand the focus back to.
   */
  overview: { section: "uploads" | null; opener: HTMLElement | null } | null = null;

  constructor(resolveOriginalUrl: (file: PreviewFile) => Promise<string>) {
    this.#resolveOriginalUrl = resolveOriginalUrl;
  }

  subscribe = (listener: () => void) => {
    this.#listeners.add(listener);
    return () => {
      this.#listeners.delete(listener);
    };
  };

  getVersion = () => this.#version;

  #emit() {
    this.#version++;
    for (const listener of this.#listeners) listener();
  }

  /** What the panel shows now. */
  get occupant(): PanelOccupant {
    if (this.viewCallId !== null) return { kind: "view", callId: this.viewCallId };
    if (this.shown) return { kind: "file" };
    if (this.overview) return { kind: "overview", section: this.overview.section };
    return { kind: "closed" };
  }

  /** Whether the panel holds anything: a file, a document being written, a view or the overview. */
  get active() {
    return this.occupant.kind !== "closed";
  }

  /** Whether a file has a renderer; without one it can only be downloaded. */
  canPreview(file: { name: string; mimetype: string }) {
    return previewKindOf(file) !== null;
  }

  /** Whether the panel shows `file`: it is the file held, and nothing covers it. */
  isOpen(file: { id: string }) {
    return this.#holds(file) && this.viewCallId === null;
  }

  #holds(file: { id: string }) {
    return this.file?.id === file.id;
  }

  /** Whether the panel holds a file, or a document being written. */
  get shown() {
    return this.file !== null || this.draft !== null;
  }

  // ---------------------------------------------------------------------
  // Overview
  // ---------------------------------------------------------------------

  /**
   * Shows the overview, open at `section`; `opener` gets the focus back when
   * it closes. A file or view on show leaves the panel first.
   */
  showOverview(section: "uploads" | null = null, opener?: HTMLElement | null) {
    this.#guarded(() => {
      this.openedByItself = false;
      if (this.viewCallId !== null) this.#closeView();
      if (this.shown) this.#close();
      this.overview = { section, opener: opener ?? null };
      this.#emit();
    });
  }

  /** Closes the overview; the focus returns to its opener unless told otherwise. */
  closeOverview(restoreFocus = true) {
    if (this.overview === null) return;
    const opener = this.overview.opener;
    this.overview = null;
    if (restoreFocus) returnFocus(opener);
    this.#emit();
  }

  // ---------------------------------------------------------------------
  // Files
  // ---------------------------------------------------------------------

  /** Shows `file` in the panel; `opener` gets the focus back when it closes. */
  open(file: PreviewFile, opener?: HTMLElement | null) {
    // The file on show stays, edits and all.
    if (this.isOpen(file) && !this.replacementFile) return this.#open(file, opener);
    this.#guarded(() => this.#open(file, opener));
  }

  #open(file: PreviewFile, opener?: HTMLElement | null) {
    this.#opener = opener ?? null;
    this.openedByItself = false;
    this.highlight = null;
    this.overview = null;
    if (this.viewCallId !== null) this.#closeView();
    if (this.draft) this.#leftDraft = this.draft.callId;
    this.draft = null;
    // Reopening a file that is already loading must not cancel its own load.
    if (this.#holds(file) && !this.replacementFile) return this.#emit();
    this.#abort?.abort();
    this.#clearReplacement();
    if (this.#holds(file)) return this.#emit();
    this.#releaseSave();
    this.file = file;
    this.#emit();
    void this.#load(file);
  }

  /** Opens `file`, or closes the panel when it already shows that file. */
  toggle(file: PreviewFile, opener?: HTMLElement | null) {
    this.#guarded(() => {
      if (this.isOpen(file)) {
        if (this.viewCallId !== null) this.#closeView();
        this.#close();
        this.#emit();
      } else this.#open(file, opener);
    });
  }

  /** Shows `file` with `passage` marked in it, opening the panel if needed. */
  showPassage(file: PreviewFile, passage: PreviewPassage, opener?: HTMLElement | null) {
    this.#guarded(() => {
      this.#open(file, opener);
      this.highlight = passage;
      this.#emit();
    });
  }

  /** A new answer begins: the panel may open by itself again. */
  beginAnswer() {
    this.#opensByItself = true;
    this.viewDismissedThisAnswer = false;
    this.#finishedDrafts.clear();
    this.#emit();
  }

  /**
   * Shows progress while the assistant writes. A loaded document stays readable;
   * a closed panel opens with the draft when it sits beside the conversation,
   * and so does one that shows something else.
   */
  write(draft: DocumentDraft) {
    if (draft.callId === this.#leftDraft || this.#finishedDrafts.has(draft.callId)) return;
    if (!this.shown || this.viewCallId !== null) {
      if (!this.besideConversation || !this.#opensByItself) return;
      this.openedByItself = true;
      if (this.viewCallId !== null) this.#closeView();
      this.overview = null;
    }
    this.#takeDraft(draft);
  }

  /**
   * Shows the document being written because the reader asked for it: after
   * closing the panel on it, or on a narrow screen, where it does not open
   * by itself. A loaded document gives way; unsaved edits ask first.
   */
  showDraft(draft: DocumentDraft) {
    if (this.#finishedDrafts.has(draft.callId)) return;
    this.#guarded(() => {
      // The reader may have been asked about their edits first, and the
      // assistant written on meanwhile: the document, once it has come, is
      // what they get to see, else the draft as it stands now.
      const finished = this.#finishedDrafts.get(draft.callId);
      if (finished) {
        this.#open(finished);
        return;
      }
      if (this.#leftDraft === draft.callId) this.#leftDraft = null;
      this.openedByItself = false;
      if (this.viewCallId !== null) this.#closeView();
      this.overview = null;
      this.#abort?.abort();
      // A save still in flight was of the document the draft replaces.
      this.#releaseSave();
      this.#clearReplacement();
      this.file = null;
      this.content = null;
      this.#takeDraft(this.draft?.callId === draft.callId ? this.draft : draft);
    });
  }

  #takeDraft(draft: DocumentDraft) {
    if (this.draft?.callId !== draft.callId) {
      this.#abort?.abort();
      this.#clearReplacement();
      if (this.status !== "ready" || !this.content) {
        this.#releaseSave();
        this.file = null;
        this.content = null;
      }
    }
    this.highlight = null;
    const previous = this.draft;
    const hasBody = !!draft.text || !!draft.sheets?.length;
    const hasPreviousBody = !!previous?.text || !!previous?.sheets?.length;
    this.draft =
      !hasBody && hasPreviousBody && previous
        ? {
            ...draft,
            title: draft.title || previous.title,
            text: previous.text,
            sheets: previous.sheets,
            showingPreviousDraft: true
          }
        : draft;
    this.#emit();
  }

  /** Keep the draft during the saved-file handoff; discard unfinished drafts. */
  endDraft() {
    if (this.replacementFile || (this.file && this.status === "loading")) return;
    if (this.draft === null) return;
    this.draft = null;
    this.#emit();
  }

  /**
   * A file the assistant just created. It takes over an open panel, as when a
   * newer version of the open document arrives; any previewable file also opens
   * a closed one, like the draft it was written as. `changed` is a passage to
   * point out in it: what an edit of the earlier version put in.
   */
  arrive(file: PreviewFile, changed: PreviewPassage | null = null, callId?: string | null) {
    if (this.#holds(file)) return;
    if (callId && callId === this.#leftDraft) {
      // Not shown, since the reader left its draft; but asked for, it is this file.
      this.#finishedDrafts.set(callId, file);
      return;
    }
    if (!this.shown || this.viewCallId !== null) {
      const opens = this.besideConversation && this.#opensByItself;
      if (!opens || !this.canPreview(file)) return;
      this.openedByItself = true;
      if (this.viewCallId !== null) this.#closeView();
      this.overview = null;
    }
    // The call that made the file is done, and so is the draft on show, which
    // the file takes over whichever call it is from.
    if (callId) this.#finishedDrafts.set(callId, file);
    if (this.draft) this.#finishedDrafts.set(this.draft.callId, file);
    const keepCurrent = !!this.file && !!this.content && this.status === "ready";
    if (!keepCurrent) {
      this.#releaseSave();
      this.highlight = changed;
      this.file = file;
    }
    this.#emit();
    void this.#load(file, keepCurrent, changed);
  }

  /**
   * The new renderer is ready: swap content and metadata together. A reader
   * who is editing keeps the text in front of them; the replacement waits.
   */
  finishReplacement(id: string) {
    if (this.replacementFile?.id !== id || !this.replacementContent) return;
    this.#replacementReady = true;
    if (this.dirty) return;
    this.#releaseSave();
    this.file = this.replacementFile;
    this.content = this.replacementContent;
    this.highlight = this.#replacementHighlight;
    this.status = "ready";
    this.draft = null;
    this.#clearReplacement();
    this.#emit();
  }

  failReplacement(id: string) {
    if (this.replacementFile?.id !== id) return;
    this.replacementContent = null;
    this.replacementError = "failed";
    this.draft = null;
    this.#emit();
  }

  retry() {
    if (this.replacementFile) {
      void this.#load(this.replacementFile, true, this.#replacementHighlight);
    } else if (this.file) void this.#load(this.file);
  }

  #clearReplacement() {
    this.replacementFile = null;
    this.replacementContent = null;
    this.replacementError = null;
    this.#replacementHighlight = null;
    this.#replacementReady = false;
  }

  async #load(file: PreviewFile, keepCurrent = false, changed: PreviewPassage | null = null) {
    this.#abort?.abort();
    const abort = (this.#abort = new AbortController());

    this.#clearReplacement();
    if (keepCurrent) {
      this.replacementFile = file;
      this.#replacementHighlight = changed;
    } else {
      this.content = null;
      this.status = "loading";
    }
    this.#emit();

    try {
      let content = this.#cache.get(file.id);
      if (!content) {
        const kind = previewKindOf(file);
        if (!kind) throw new Error("File has no preview");
        const url = await this.#resolveOriginalUrl(file);
        if (abort.signal.aborted) return;
        content = await loadPreview(file, kind, url, abort.signal);
        if (abort.signal.aborted) return;
        this.#remember(file.id, content);
      }
      if (keepCurrent) {
        // The panel prepares the renderer offscreen and commits only when ready.
        this.replacementContent = content;
        this.#emit();
        return;
      }
      this.content = content;
      this.status = "ready";
    } catch (error) {
      if (abort.signal.aborted) return;
      const failure = error instanceof PreviewTooLargeError ? "too_large" : "failed";
      if (keepCurrent) this.replacementError = failure;
      else this.status = failure;
    }
    this.draft = null;
    this.#emit();
  }

  #remember(id: string, content: PreviewContent) {
    this.#cache.set(id, content);
    if (this.#cache.size > CACHED_PREVIEWS) {
      this.#cache.delete(this.#cache.keys().next().value!);
    }
  }

  // ---------------------------------------------------------------------
  // Editing
  // ---------------------------------------------------------------------

  /**
   * The text of the document `fileId` as the reader has it now, or null once
   * it is the file's text again.
   */
  setEdits(fileId: string, text: string | null) {
    this.#edits = text === null ? null : { fileId, text };
    this.dirty = text !== null;
    // Undone back to the saved text: a newer version that waited can show.
    if (text === null) this.#showReplacement();
    this.#emit();
  }

  /** The reader's unsaved text of `file`, for an editor that shows it afresh. */
  editsOf(file: { id: string }): string | null {
    return this.#edits?.fileId === file.id ? this.#edits.text : null;
  }

  #clearEdits() {
    this.#edits = null;
    this.dirty = false;
    this.#releaseSave();
  }

  #releaseSave() {
    this.#saveRequest = null;
    this.saving = false;
  }

  /**
   * A save belongs to the editing session it was started in, even if its
   * panel remounts. Leaving or discarding that session detaches the save's
   * response from the preview: `apply` then does nothing and says so.
   */
  beginSave() {
    const request = Symbol("document-save");
    this.#saveRequest = request;
    this.saving = true;
    this.#emit();
    return {
      apply: (file: PreviewFile, markdown: string) => {
        if (this.#saveRequest !== request) return false;
        this.saved(file, markdown);
        return true;
      },
      finish: () => {
        if (this.#saveRequest !== request) return;
        this.#releaseSave();
        this.#emit();
      }
    };
  }

  /** The reader let their edits go; a replacement that waited then shows. */
  dropEdits() {
    this.#clearEdits();
    this.#showReplacement();
    this.#emit();
  }

  /** The reader keeps editing after all. */
  keepEditing() {
    if (this.pendingDiscard === null) return;
    this.pendingDiscard = null;
    this.#emit();
  }

  setShowChanges(on: boolean) {
    if (this.showChanges === on) return;
    this.showChanges = on;
    this.#emit();
  }

  /**
   * The reader's edit was saved as `file`, whose text is `markdown`. It is
   * the document on show now; a replacement staged meanwhile is dropped,
   * since the reader's version is the one they asked for.
   */
  saved(file: PreviewFile, markdown: string) {
    const content: PreviewContent = { kind: "markdown", text: markdown, truncated: false };
    this.#remember(file.id, content);
    this.#abort?.abort();
    this.#clearReplacement();
    this.file = file;
    this.content = content;
    this.status = "ready";
    this.highlight = null;
    this.draft = null;
    this.#clearEdits();
    // A question about discarding the edits, asked while the save was in
    // flight, is settled: they are saved.
    this.pendingDiscard = null;
    this.#emit();
  }

  /** The text of a Markdown document, for comparing versions; null when it cannot be read. */
  async loadText(file: PreviewFile): Promise<string | null> {
    let content = this.#cache.get(file.id);
    if (!content) {
      try {
        const url = await this.#resolveOriginalUrl(file);
        content = await loadPreview(file, "markdown", url, new AbortController().signal);
        this.#remember(file.id, content);
      } catch {
        return null;
      }
    }
    return content.kind === "markdown" ? content.text : null;
  }

  // Runs `action` at once, or once the reader has agreed to lose their edits.
  #guarded(action: () => void) {
    if (!this.dirty) {
      action();
      return;
    }
    this.pendingDiscard = {
      proceed: () => {
        this.pendingDiscard = null;
        this.#clearEdits();
        action();
        this.#emit();
      }
    };
    this.#emit();
  }

  #showReplacement() {
    if (this.#replacementReady && this.replacementFile && this.replacementContent) {
      this.finishReplacement(this.replacementFile.id);
    }
  }

  // ---------------------------------------------------------------------
  // Quotes
  // ---------------------------------------------------------------------

  /** Makes text selected in the open file the quote of the next question. */
  quoteSelection(selected: string, locator: string | null) {
    const text = tidyQuoteText(selected);
    if (!this.file || !text) return;
    this.quote = { fileId: this.file.id, fileName: this.file.name, text, locator };
    // On narrow screens the preview covers the composer; return to the
    // chat. Unsaved edits would go with the panel, so that asks first.
    if (!this.besideConversation) this.close();
    this.#emit();
  }

  /**
   * Makes text an interactive view says the reader selected in it the quote
   * of the next question. No text withdraws that view's quote, and only its own.
   */
  quoteView(callId: string, name: string, selected: string) {
    const text = tidyQuoteText(selected);
    if (text) {
      // The name closes the quote on a line of its own.
      const fileName = name.replace(/\s+/g, " ").trim();
      this.quote = { viewCallId: callId, fileName, text, locator: null };
    } else if (this.quote?.viewCallId === callId) {
      this.quote = null;
    } else return;
    this.#emit();
  }

  /** Drops the quote waiting in the composer. */
  clearQuote() {
    if (this.quote === null) return;
    this.quote = null;
    this.#emit();
  }

  /**
   * Puts a quote back in the composer: a question that was sent with it never
   * reached the backend. A quote the reader made meanwhile stays.
   */
  restoreQuote(quote: PreviewQuote | null) {
    if (quote === null || this.quote !== null) return;
    this.quote = quote;
    this.#emit();
  }

  /** Offers `text` as the next message; the composer takes it with `takeSuggestion`. */
  suggestMessage(text: string) {
    this.suggestion = text;
    this.#emit();
  }

  takeSuggestion(): string | null {
    const text = this.suggestion;
    if (text === null) return null;
    this.suggestion = null;
    this.#emit();
    return text;
  }

  // ---------------------------------------------------------------------
  // Views
  // ---------------------------------------------------------------------

  /** Shows the view of `callId` over whatever file is open; the file stays loaded beneath. */
  openView(callId: string) {
    this.#guarded(() => {
      this.viewCallId = callId;
      this.overview = null;
      this.#emit();
    });
  }

  /** Returning inline keeps the same app instance and its state. */
  closeView() {
    if (this.viewCallId === null) return;
    this.#closeView();
    this.#emit();
  }

  /** The user closes the view's panel. */
  dismissView() {
    this.viewDismissedThisAnswer = true;
    this.closeView();
  }

  #closeView() {
    this.viewCallId = null;
    // A maximised panel stays so for the file beneath; an empty one lets go.
    if (!this.shown) this.maximised = false;
  }

  /** Where the shown view is laid out; the frame positions itself over it. */
  setViewTarget(target: HTMLElement | null) {
    if (this.viewTarget === target) return;
    this.viewTarget = target;
    this.#emit();
  }

  offerView(callId: string, offered: boolean) {
    const had = this.offeredViews.has(callId);
    if (had === offered) return;
    if (offered) this.offeredViews.add(callId);
    else this.offeredViews.delete(callId);
    this.#emit();
  }

  // ---------------------------------------------------------------------
  // Layout
  // ---------------------------------------------------------------------

  setBesideConversation(beside: boolean) {
    if (this.besideConversation === beside) return;
    this.besideConversation = beside;
    this.#emit();
  }

  setMaximised(maximised: boolean) {
    if (this.maximised === maximised) return;
    this.maximised = maximised;
    this.#emit();
  }

  /** Closes the file on show (a view over it closes first), asking first when edits would be lost. */
  close() {
    this.#guarded(() => {
      if (this.viewCallId !== null) this.#closeView();
      this.#close();
      this.#emit();
    });
  }

  /** Closes whatever the panel shows, asking first when edits would be lost. */
  closeAll() {
    this.#guarded(() => {
      if (this.viewCallId !== null) this.#closeView();
      if (this.shown) this.#close();
      this.overview = null;
      this.#emit();
    });
  }

  #close() {
    this.#releaseSave();
    if (this.draft) this.#leftDraft = this.draft.callId;
    this.#abort?.abort();
    this.#abort = null;
    this.#clearReplacement();
    this.#opensByItself = false;
    this.maximised = false;
    this.file = null;
    this.draft = null;
    this.content = null;
    this.highlight = null;
    this.#clearEdits();
    returnFocus(this.#opener);
    this.#opener = null;
  }
}

/**
 * Gives the focus back to the control that opened the panel. A modal sheet
 * still open keeps it inert, so it is tried again once the sheet has gone,
 * unless something else (the panel's next occupant) has taken the focus.
 */
function returnFocus(opener: HTMLElement | null) {
  if (!opener?.isConnected) return;
  opener.focus();
  if (document.activeElement === opener) return;
  requestAnimationFrame(() => {
    const lost = document.activeElement === null || document.activeElement === document.body;
    if (lost && opener.isConnected) opener.focus();
  });
}
