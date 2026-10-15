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
  // A file has arrived for these calls. Late draft effects cannot take over
  // either its download or its completed preview.
  #finishedDrafts = new Set<string>();
  #replacementHighlight: PreviewPassage | null = null;
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
    this.openedByItself = false;
    if (this.viewCallId !== null) this.#closeView();
    if (this.shown) this.#close();
    this.overview = { section, opener: opener ?? null };
    this.#emit();
  }

  /** Closes the overview; the focus returns to its opener unless told otherwise. */
  closeOverview(restoreFocus = true) {
    if (this.overview === null) return;
    const opener = this.overview.opener;
    this.overview = null;
    if (restoreFocus && opener?.isConnected) opener.focus();
    this.#emit();
  }

  // ---------------------------------------------------------------------
  // Files
  // ---------------------------------------------------------------------

  /** Shows `file` in the panel; `opener` gets the focus back when it closes. */
  open(file: PreviewFile, opener?: HTMLElement | null) {
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
    this.file = file;
    this.#emit();
    void this.#load(file);
  }

  /** Opens `file`, or closes the panel when it already shows that file. */
  toggle(file: PreviewFile, opener?: HTMLElement | null) {
    if (this.isOpen(file)) this.close();
    else this.open(file, opener);
  }

  /** Shows `file` with `passage` marked in it, opening the panel if needed. */
  showPassage(file: PreviewFile, passage: PreviewPassage, opener?: HTMLElement | null) {
    this.open(file, opener);
    this.highlight = passage;
    this.#emit();
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
    if (this.draft?.callId !== draft.callId) {
      this.#abort?.abort();
      this.#clearReplacement();
      if (this.status !== "ready" || !this.content) {
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
    if ((callId && callId === this.#leftDraft) || this.#holds(file)) return;
    if (!this.shown || this.viewCallId !== null) {
      const opens = this.besideConversation && this.#opensByItself;
      if (!opens || !this.canPreview(file)) return;
      this.openedByItself = true;
      if (this.viewCallId !== null) this.#closeView();
      this.overview = null;
    }
    if (this.draft) this.#finishedDrafts.add(this.draft.callId);
    const keepCurrent = !!this.file && !!this.content && this.status === "ready";
    if (!keepCurrent) {
      this.highlight = changed;
      this.file = file;
    }
    this.#emit();
    void this.#load(file, keepCurrent, changed);
  }

  /** The new renderer is ready: swap content and metadata together. */
  finishReplacement(id: string) {
    if (this.replacementFile?.id !== id || !this.replacementContent) return;
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
        this.#cache.set(file.id, content);
        if (this.#cache.size > CACHED_PREVIEWS) {
          this.#cache.delete(this.#cache.keys().next().value!);
        }
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

  // ---------------------------------------------------------------------
  // Quotes
  // ---------------------------------------------------------------------

  /** Makes text selected in the open file the quote of the next question. */
  quoteSelection(selected: string, locator: string | null) {
    const text = tidyQuoteText(selected);
    if (!this.file || !text) return;
    this.quote = { fileId: this.file.id, fileName: this.file.name, text, locator };
    // On narrow screens the preview covers the composer; return to the chat.
    if (!this.besideConversation) this.#close();
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
    this.viewCallId = callId;
    this.overview = null;
    this.#emit();
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

  /** Closes the file on show (a view over it closes first). */
  close() {
    if (this.viewCallId !== null) this.#closeView();
    this.#close();
    this.#emit();
  }

  /** Closes whatever the panel shows. */
  closeAll() {
    if (this.viewCallId !== null) this.#closeView();
    if (this.shown) this.#close();
    this.overview = null;
    this.#emit();
  }

  #close() {
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
    if (this.#opener?.isConnected) this.#opener.focus();
    this.#opener = null;
  }
}
