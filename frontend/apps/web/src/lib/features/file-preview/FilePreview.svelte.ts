import { getContext, setContext } from "svelte";
import type { getAttachmentUrlService } from "$lib/features/attachments/AttachmentUrlService.svelte";
import { loadPreview, PreviewTooLargeError, type PreviewContent } from "./loadPreview";
import { previewKindOf, type PreviewFile } from "./previewKind";

type AttachmentUrls = ReturnType<typeof getAttachmentUrlService>;

/** An excerpt of a file the user selected to ask about. */
export type PreviewQuote = {
  fileId: string;
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
  // A file has arrived for these calls. Late draft effects cannot take over
  // either its download or its completed preview.
  // eslint-disable-next-line svelte/prefer-svelte-reactivity -- transition guard, never rendered
  #finishedDrafts = new Set<string>();

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

  #clearReplacement() {
    this.replacementFile = null;
    this.replacementContent = null;
    this.replacementError = null;
    this.#replacementHighlight = null;
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
  /** Whether the panel covers the conversation instead of sharing the width with it. */
  maximised = $state(false);
  /**
   * Something else shown in the panel over the file (an interactive tool
   * view). The file stays loaded beneath it and is on show again when the
   * cover goes; a file that takes the panel asks the cover to leave.
   */
  cover = $state.raw<PreviewCover | null>(null);

  constructor(urls: AttachmentUrls) {
    this.#urls = urls;
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
    if ((callId && callId === this.#leftDraft) || this.#holds(file)) return;
    if (!this.shown || this.cover) {
      const opens = this.besideConversation && this.#opensByItself;
      if (!opens || !this.canPreview(file)) return;
      this.openedByItself = true;
      this.cover?.leave();
    }
    if (this.draft) this.#finishedDrafts.add(this.draft.callId);
    const keepCurrent = !!this.file && !!this.content && this.status === "ready";
    if (!keepCurrent) {
      this.highlight = changed;
      this.file = file;
    }
    void this.#load(file, keepCurrent, changed);
  }

  /** Shows `file` with `passage` marked in it, opening the panel if needed. */
  showPassage(file: PreviewFile, passage: PreviewPassage, opener?: HTMLElement | null) {
    this.open(file, opener);
    this.highlight = passage;
  }

  /** Makes text selected in the open file the quote of the next question. */
  quoteSelection(selected: string, locator: string | null) {
    const text = tidyQuoteText(selected);
    if (this.file && text) {
      this.quote = { fileId: this.file.id, fileName: this.file.name, text, locator };
      // On narrow screens the preview covers the composer; return to the chat.
      if (!this.besideConversation) this.close();
    }
  }

  /** Opens `file`, or closes the panel when it already shows that file. */
  toggle(file: PreviewFile, opener?: HTMLElement | null) {
    if (this.isOpen(file)) this.close();
    else this.open(file, opener);
  }

  close() {
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
        this.#cache.set(file.id, content);
        if (this.#cache.size > CACHED_PREVIEWS) {
          this.#cache.delete(this.#cache.keys().next().value!);
        }
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
