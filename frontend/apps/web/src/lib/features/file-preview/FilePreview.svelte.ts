import { getContext, setContext } from "svelte";
import type { getAttachmentUrlService } from "$lib/features/attachments/AttachmentUrlService.svelte";
import { loadPreview, PreviewTooLargeError, type PreviewContent } from "./loadPreview";
import { previewKindOf, type PreviewFile } from "./previewKind";

type AttachmentUrls = ReturnType<typeof getAttachmentUrlService>;

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

/** A passage to mark in a preview. */
export type PreviewPassage = { text: string; locator: string | null };

/** The other formats a document can be handed over in. */
export type DocumentExport = {
  availability: () => Promise<
    import("@eneo/eneo-js").components["schemas"]["DocumentExportAvailability"]
  >;
  exportAs: (format: "docx" | "pdf") => Promise<Blob>;
};

/** Whatever is shown in the panel over the file; `leave` takes it out of the panel. */
export type PreviewCover = { leave: () => void };

/** How a reader's edit of a document is kept: as the document's next version. */
export type DocumentSaver = {
  save: (markdown: string) => Promise<PreviewFile>;
};

/** Actual document input shown while the assistant is still writing it. */
export type { DocumentDraft as PreviewDraft } from "../chat/documentDraft";
import type { DocumentDraft as PreviewDraft } from "../chat/documentDraft";

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
 * The file shown in the conversation's preview panel, and its loaded content.
 *
 * Any file chip in the conversation opens its file here. The state lives outside
 * the panel markup so the side panel and the narrow-screen sheet present the
 * same preview when the layout crosses the breakpoint.
 */
export class FilePreview {
  #urls: AttachmentUrls;
  // eslint-disable-next-line svelte/prefer-svelte-reactivity -- a cache, never rendered
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
  // eslint-disable-next-line svelte/prefer-svelte-reactivity -- transition guard, never rendered
  #finishedDrafts = new Map<string, PreviewFile>();

  file = $state.raw<PreviewFile | null>(null);
  /**
   * The document being written. An already loaded file stays visible while
   * its replacement is prepared; otherwise the draft itself is shown.
   */
  draft = $state.raw<PreviewDraft | null>(null);
  /**
   * Whether the layout shows the panel beside the conversation. As a sheet
   * over the conversation it never opens by itself.
   */
  besideConversation = $state(false);
  /** Whether the panel was last opened by the assistant's writing, not by the reader. */
  openedByItself = false;
  status = $state<"loading" | "ready" | "too_large" | "failed">("loading");
  content = $state.raw<PreviewContent | null>(null);
  /** Stage automatic replacements without tearing down the reader's current view. */
  replacementFile = $state.raw<PreviewFile | null>(null);
  replacementContent = $state.raw<PreviewContent | null>(null);
  replacementError = $state<"failed" | "too_large" | null>(null);
  #replacementHighlight: PreviewPassage | null = null;
  #replacementReady = false;

  #clearReplacement() {
    this.replacementFile = null;
    this.replacementContent = null;
    this.replacementError = null;
    this.#replacementHighlight = null;
    this.#replacementReady = false;
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
  }

  failReplacement(id: string) {
    if (this.replacementFile?.id !== id) return;
    this.replacementContent = null;
    this.replacementError = "failed";
    this.draft = null;
  }
  /**
   * Text selected in a preview and handed to the composer, which sends it with
   * the next question. It outlives the panel: closing the preview keeps it.
   */
  quote = $state.raw<PreviewQuote | null>(null);
  /** A passage to point out in the open file: a quote the user asked to see in place. */
  highlight = $state.raw<PreviewPassage | null>(null);
  /**
   * The reader has changed the open document's text. Edits live in the editor
   * until the reader saves them as a new version, so nothing is written on a
   * keystroke; what would lose them asks first.
   */
  dirty = $state(false);
  /** Shared across panel remounts so a pending save keeps its document read-only. */
  saving = $state(false);
  #saveRequest: symbol | null = null;
  // The edited text itself, so an editor torn down and mounted again (the
  // layout crosses its breakpoint) shows the document as the reader left it.
  #edits: { fileId: string; text: string } | null = null;
  /**
   * Whether the document on show marks what it changed against the version
   * before it. Off until the reader asks: a version that rewrites the
   * document would otherwise open as a strike-through of all its old text.
   */
  showChanges = $state(false);
  /**
   * Something would take the editor away (another file, the panel closing)
   * while edits are unsaved; it waits for the reader to decide.
   */
  pendingDiscard = $state.raw<{ proceed: () => void } | null>(null);
  /** Whether the panel covers the conversation instead of sharing the width with it. */
  maximised = $state(false);
  /**
   * Something else shown in the panel over the file (an interactive tool
   * view). The file stays loaded beneath it and is on show again when the
   * cover goes; a file that takes the panel asks the cover to leave.
   */
  cover = $state.raw<PreviewCover | null>(null);
  /**
   * The panel's overview of everything the conversation has to show, with the
   * section it opened on, the upload group it points at and the element to
   * hand the focus back to. It lives here so a file bundle in a message can
   * open it as the panel's own controls do; the layout decides how it is shown.
   */
  overview = $state.raw<{
    section: "uploads" | null;
    /** The question whose uploads the overview marks; see `uploadGroupKey`. */
    group: string | null;
    opener: string | null;
  } | null>(null);

  constructor(urls: AttachmentUrls) {
    this.#urls = urls;
  }

  /** Whether the panel shows the overview. */
  get overviewShown() {
    return this.overview !== null;
  }

  /** Whether the reader has edits that are not saved. */
  get unsaved() {
    return this.dirty;
  }

  /**
   * The text of the document `fileId` as the reader has it now, or null once
   * it is the file's text again.
   */
  setEdits(fileId: string, text: string | null) {
    this.#edits = text === null ? null : { fileId, text };
    this.dirty = text !== null;
    if (text === null) this.#showReplacement();
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
   * A save belongs to the current editing session, even if its panel remounts.
   * Leaving or discarding that session detaches its response from the preview.
   */
  beginSave() {
    const request = Symbol("document-save");
    this.#saveRequest = request;
    this.saving = true;
    return {
      apply: (file: PreviewFile, markdown: string) => {
        if (this.#saveRequest !== request) return false;
        this.saved(file, markdown);
        return true;
      },
      finish: () => {
        if (this.#saveRequest === request) this.#releaseSave();
      }
    };
  }

  /** The reader let their edits go; a replacement that waited then shows. */
  dropEdits() {
    this.#clearEdits();
    this.#showReplacement();
  }

  /** The text of a Markdown document, for comparing versions; null when it cannot be read. */
  async loadText(file: PreviewFile): Promise<string | null> {
    let content = this.#cache.get(file.id);
    if (!content) {
      try {
        const url = await this.#urls.resolveOriginalUrl(file);
        content = await loadPreview(file, "markdown", url, new AbortController().signal);
        this.#remember(file.id, content);
      } catch {
        return null;
      }
    }
    return content.kind === "markdown" ? content.text : null;
  }

  /** The reader keeps editing after all. */
  keepEditing() {
    this.pendingDiscard = null;
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
    this.pendingDiscard = null;
  }

  // Runs `action` at once, or once the reader has agreed to lose their edits.
  #guarded(action: () => void) {
    if (!this.unsaved) {
      action();
      return;
    }
    this.pendingDiscard = {
      proceed: () => {
        this.pendingDiscard = null;
        this.#clearEdits();
        action();
      }
    };
  }

  #showReplacement() {
    if (this.#replacementReady && this.replacementFile && this.replacementContent) {
      this.finishReplacement(this.replacementFile.id);
    }
  }

  #remember(id: string, content: PreviewContent) {
    this.#cache.set(id, content);
    if (this.#cache.size > CACHED_PREVIEWS) {
      this.#cache.delete(this.#cache.keys().next().value!);
    }
  }

  /**
   * Shows the overview, open at `section` and marking the upload `group`;
   * `opener` gets the focus back when it closes. A file or view on show
   * leaves the panel first.
   */
  showOverview(
    section: "uploads" | null = null,
    opener?: HTMLElement | null,
    group: string | null = null
  ) {
    this.#guarded(() => {
      this.cover?.leave();
      if (this.shown) this.#close();
      if (opener && !opener.id) opener.id = `preview-opener-${crypto.randomUUID()}`;
      this.overview = { section, group, opener: opener?.id ?? null };
    });
  }

  /** Closes the overview; the focus returns to its opener unless told otherwise. */
  closeOverview(restoreFocus = true) {
    const opener = this.overview?.opener;
    if (this.overview === null) return;
    this.overview = null;
    if (restoreFocus && opener && typeof document !== "undefined") {
      document.getElementById(opener)?.focus();
    }
  }

  /** Whether `element` is what opened the overview on show. */
  isOverviewOpener(element: HTMLElement | null) {
    // The overview is read first: an element without an id yet must still
    // leave a dependency on it, or the answer never updates once it opens.
    const opener = this.overview?.opener;
    return !!opener && !!element && element.id === opener;
  }

  /** Whether a file has a renderer; without one it can only be downloaded. */
  canPreview(file: { name: string; mimetype: string }) {
    return previewKindOf(file) !== null;
  }

  /** Whether the panel shows `file`: it is the file held, and nothing covers it. */
  isOpen(file: { id: string }) {
    return this.#holds(file) && !this.cover;
  }

  #holds(file: { id: string }) {
    return this.file?.id === file.id;
  }

  /** Whether the panel holds anything: a file, or a document being written. */
  get shown() {
    return this.file !== null || this.draft !== null;
  }

  /** Shows `file` in the panel; `opener` gets the focus back when it closes. */
  open(file: PreviewFile, opener?: HTMLElement | null) {
    this.#guarded(() => this.#open(file, opener));
  }

  #open(file: PreviewFile, opener?: HTMLElement | null) {
    this.#opener = opener ?? null;
    this.openedByItself = false;
    this.highlight = null;
    this.cover?.leave();
    if (this.draft) this.#leftDraft = this.draft.callId;
    this.draft = null;
    // Reopening a file that is already loading must not cancel its own load.
    if (this.#holds(file) && !this.replacementFile) return;
    this.#abort?.abort();
    this.#clearReplacement();
    if (this.#holds(file)) return;
    this.#releaseSave();
    this.file = file;
    void this.#load(file);
  }

  /** A new answer begins: the panel may open by itself again. */
  beginAnswer() {
    this.#opensByItself = true;
    this.#finishedDrafts.clear();
  }

  /**
   * Shows progress while the assistant writes. A loaded document stays readable;
   * a closed panel opens with the draft when it sits beside the conversation,
   * and so does one that shows something else.
   */
  write(draft: PreviewDraft) {
    if (draft.callId === this.#leftDraft || this.#finishedDrafts.has(draft.callId)) return;
    if (!this.shown || this.cover) {
      if (!this.besideConversation || !this.#opensByItself) return;
      this.openedByItself = true;
      this.cover?.leave();
    }
    this.#takeDraft(draft);
  }

  /**
   * Shows the document being written because the reader asked for it: after
   * closing the panel on it, or on a narrow screen, where it does not open
   * by itself. A loaded document gives way; unsaved edits ask first.
   */
  showDraft(draft: PreviewDraft) {
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
      this.cover?.leave();
      this.#abort?.abort();
      // A save still in flight was of the document the draft replaces.
      this.#releaseSave();
      this.#clearReplacement();
      this.file = null;
      this.content = null;
      this.#takeDraft(this.draft?.callId === draft.callId ? this.draft : draft);
    });
  }

  #takeDraft(draft: PreviewDraft) {
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
  }

  /** Keep the draft during the saved-file handoff; discard unfinished drafts. */
  endDraft() {
    if (this.replacementFile || (this.file && this.status === "loading")) return;
    this.draft = null;
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
    if (!this.shown || this.cover) {
      const opens = this.besideConversation && this.#opensByItself;
      if (!opens || !this.canPreview(file)) return;
      this.openedByItself = true;
      this.cover?.leave();
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
    void this.#load(file, keepCurrent, changed);
  }

  /** Shows `file` with `passage` marked in it, opening the panel if needed. */
  showPassage(file: PreviewFile, passage: PreviewPassage, opener?: HTMLElement | null) {
    this.#guarded(() => {
      this.#open(file, opener);
      this.highlight = passage;
    });
  }

  /** Makes text selected in the open file the quote of the next question. */
  quoteSelection(selected: string, locator: string | null) {
    const text = tidyQuoteText(selected);
    if (this.file && text) {
      this.quote = { fileId: this.file.id, fileName: this.file.name, text, locator };
      // On narrow screens the preview covers the composer; return to the
      // chat. Unsaved edits would go with the panel, so that asks first.
      if (!this.besideConversation) this.close();
    }
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
    }
  }

  /** Opens `file`, or closes the panel when it already shows that file. */
  toggle(file: PreviewFile, opener?: HTMLElement | null) {
    this.#guarded(() => (this.isOpen(file) ? this.#close() : this.#open(file, opener)));
  }

  close() {
    this.#guarded(() => this.#close());
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
    if (this.#opener?.isConnected) this.#opener.focus();
    this.#opener = null;
  }

  retry() {
    if (this.replacementFile) {
      void this.#load(this.replacementFile, true, this.#replacementHighlight);
    } else if (this.file) void this.#load(this.file);
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

    try {
      let content = this.#cache.get(file.id);
      if (!content) {
        const kind = previewKindOf(file);
        if (!kind) throw new Error("File has no preview");
        const url = await this.#urls.resolveOriginalUrl(file);
        if (abort.signal.aborted) return;
        content = await loadPreview(file, kind, url, abort.signal);
        if (abort.signal.aborted) return;
        this.#remember(file.id, content);
      }
      if (keepCurrent) {
        // The panel prepares the renderer offscreen and commits only when ready.
        this.replacementContent = content;
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
  }
}

const contextKey = Symbol("File preview");

export function initFilePreview(urls: AttachmentUrls) {
  return setContext(contextKey, new FilePreview(urls));
}

/**
 * The preview panel of the surrounding conversation, or undefined where
 * messages render without one (a read-only transcript); chips then keep to
 * downloading.
 */
export function getFilePreview(): FilePreview | undefined {
  return getContext<FilePreview | undefined>(contextKey);
}
