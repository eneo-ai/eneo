"use client";

import { Button } from "@astryxdesign/core/Button";
import type { Editor } from "@tiptap/core";
import { TextSelection } from "@tiptap/pm/state";
import { CellSelection } from "@tiptap/pm/tables";
import { EditorContent, useEditor } from "@tiptap/react";
import { BubbleMenu } from "@tiptap/react/menus";
import { TextQuote } from "lucide-react";
import { useTranslations } from "use-intl";
import {
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
  useState,
  type Ref
} from "react";
import { signedFileUrl } from "@/features/files/signed-file-url";
import { browserApi } from "@/lib/api/browser";
import { ANSWER_TEXT_CLASS } from "@/components/ai-elements/message";
import { useNonce } from "@/components/providers/nonce";
import { cn } from "@/lib/utils";
import { changesBetween } from "./editor/changes";
import { replaceContent } from "./editor/content";
import { documentExtensions, withFinalNewline } from "./editor/extensions";
import {
  cellSelectionQuote,
  findPassageSpans,
  locateSelection,
  selectedText
} from "./editor/passages";
import type { PreviewPassage } from "./preview-kind";

/** The document as the reader has it, and a way to let their edits go. */
export type DocumentEditorHandle = {
  /** The document as the reader has it now. */
  getMarkdown: () => string;
  /** Drops the reader's edits and shows the file's text again. */
  reset: () => void;
};

export type DocumentEditorProps = {
  /** The document as Markdown. A change replaces the content unless the reader has unsaved edits. */
  markdown: string;
  /**
   * The reader's unsaved text of the document, left by an editor that was
   * torn down: shown in place of `markdown`, and still unsaved. Read when
   * the editor is made.
   */
  edits?: string | null;
  editable?: boolean;
  /** A passage to mark and scroll to; null clears the mark. */
  highlight?: PreviewPassage | null;
  /** The version before this one, as Markdown; what changed against it is marked. */
  previousMarkdown?: string | null;
  /** Called with the selected text, and where it stands, when the reader quotes it. */
  onQuote?: (text: string, locator: string | null) => void;
  /**
   * The document's text as the reader has it, whenever they change it, and
   * null once it is `markdown` again. Never called for a `markdown` update,
   * nor for the editor's own tidying of a loaded document.
   */
  onChange?: (text: string | null) => void;
  /** The reader asked to save (Mod+S) while editing. */
  onSave?: () => void;
  /** Each `markdown` value has been laid out. */
  onRender?: () => void;
  /** The first content has been laid out. */
  onReady?: () => void;
  ref?: Ref<DocumentEditorHandle>;
};

// An image of the conversation is loaded from a short-lived link; a file the
// reader may not load shows its alt text instead.
const resolveImage = (fileId: string) =>
  signedFileUrl(browserApi, fileId, "inline").catch(() => undefined);

// Once the document is marked edited, a further keystroke is marked this
// long after the last, since marking serialises the whole document.
const EDIT_DELAY = 150;

// The quote action floats over the selection, positioned within the editor so
// it scrolls with the text and no transformed ancestor of the panel throws it off.
const MENU_OPTIONS = {
  strategy: "absolute",
  placement: "top",
  offset: 8,
  flip: true,
  shift: { padding: 8 }
} as const;

/** Scrolls whatever scrolls the editor to centre the position. */
function reveal(editor: Editor, pos: number) {
  let scroller = editor.view.dom.parentElement;
  while (scroller) {
    const style = getComputedStyle(scroller);
    if (/auto|scroll/.test(style.overflowY) && scroller.scrollHeight > scroller.clientHeight) {
      break;
    }
    scroller = scroller.parentElement;
  }
  if (!scroller) return;
  const coords = editor.view.coordsAtPos(pos);
  const frame = scroller.getBoundingClientRect();
  scroller.scrollBy({ top: (coords.top + coords.bottom) / 2 - (frame.top + frame.height / 2) });
}

/**
 * A generated Markdown document in a TipTap editor: read, quoted from, and
 * edited in place. Edits stay in the editor until the reader saves them; a
 * `markdown` update (a streaming draft grows, another version opens) replaces
 * the content unless there are unsaved edits.
 */
export function DocumentEditor({
  markdown,
  edits = null,
  editable = false,
  highlight = null,
  previousMarkdown = null,
  onQuote,
  onChange,
  onSave,
  onRender,
  onReady,
  ref
}: DocumentEditorProps) {
  const t = useTranslations();
  const nonce = useNonce();
  // The reader's edits win over a `markdown` update until they are saved or dropped.
  const dirty = useRef(false);
  // The Markdown the editor last took, so the same text is not parsed again.
  const applied = useRef(markdown);
  // The document as loaded, serialised: what the reader's text is compared
  // with. The file's own Markdown does not serve, since a document does not
  // come back byte for byte (a table's columns are padded, for one).
  const baseline = useRef<string | null>(null);
  // Content is being put in place; the editor's own tidying of it is no edit.
  const applying = useRef(false);
  // Edits left by an earlier editor of this document, taken once at creation.
  const left = useRef(edits);
  // A keystroke whose mark is still waiting, and the editor it was made in.
  const pending = useRef<{ timer: number; editor: Editor } | null>(null);
  // Bumped when the document changed under the decorations, so they are placed again.
  const [rendered, setRendered] = useState(0);
  const callbacks = useRef({ onChange, onSave, onRender, onReady });
  useLayoutEffect(() => {
    callbacks.current = { onChange, onSave, onRender, onReady };
  });

  /**
   * Compares the reader's text with the document as loaded, and tells of a
   * difference. Reads only refs, so the editor's options and the handle can
   * call it without depending on a render.
   */
  const noteEdit = useCallback((current: Editor) => {
    pending.current = null;
    const text = withFinalNewline(current.getMarkdown());
    const changed = text !== baseline.current;
    if (!changed && !dirty.current) return;
    dirty.current = changed;
    callbacks.current.onChange?.(changed ? text : null);
  }, []);

  /** Marks an edit that is still waiting, so whatever reads the mark reads it current. */
  const flush = useCallback(() => {
    const waiting = pending.current;
    if (!waiting) return;
    clearTimeout(waiting.timer);
    if (waiting.editor.isDestroyed) pending.current = null;
    else noteEdit(waiting.editor);
  }, [noteEdit]);

  /** Puts `next` in `current` as the document the reader's text is compared with. */
  function apply(current: Editor, next: string) {
    applying.current = true;
    try {
      replaceContent(current, next);
    } finally {
      applying.current = false;
    }
    applied.current = next;
    baseline.current = withFinalNewline(current.getMarkdown());
  }

  const editor = useEditor(
    {
      // The editor is made in the browser: the page is served without it.
      immediatelyRender: false,
      injectNonce: nonce,
      extensions: documentExtensions({
        resolveImage,
        pageBreakLabel: t("file_preview_page_break")
      }),
      content: markdown,
      contentType: "markdown",
      editable,
      editorProps: {
        attributes: {
          class: cn(
            ANSWER_TEXT_CLASS,
            "document-prose focus-visible:outline-ring rounded-ax-container mx-auto max-w-[72ch] p-6 break-words focus-visible:outline-2 focus-visible:-outline-offset-2"
          )
        },
        handleKeyDown: (_view, event) => {
          if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
            event.preventDefault();
            flush();
            callbacks.current.onSave?.();
            return true;
          }
          return false;
        }
      },
      // A keystroke only marks the document edited; nothing is saved here. The
      // mark compares text with the document as loaded, since the editor also
      // tidies a loaded document (a paragraph to type in after a final code
      // block) without changing what it says, and a reader cannot edit a
      // document that is read-only. The first keystroke is marked at once, so
      // whatever guards unsaved edits sees them; a burst that follows is marked
      // once, a moment after its last.
      onUpdate: ({ editor: current }) => {
        if (applying.current || baseline.current === null || !current.isEditable) return;
        if (pending.current) clearTimeout(pending.current.timer);
        if (!dirty.current) noteEdit(current);
        else {
          pending.current = {
            editor: current,
            timer: window.setTimeout(() => noteEdit(current), EDIT_DELAY)
          };
        }
      }
    },
    []
  );

  // The first content is in the page once the editor exists. The baseline is
  // taken here rather than on the editor's own create event, which comes a
  // tick later than the first updates the mounted view sends.
  useEffect(() => {
    if (!editor) return;
    baseline.current ??= withFinalNewline(editor.getMarkdown());
    // Edits left by an earlier editor of this document take the place of the
    // loaded text, compared with it as before.
    if (left.current !== null) {
      applying.current = true;
      try {
        replaceContent(editor, left.current);
      } finally {
        applying.current = false;
      }
      left.current = null;
      dirty.current = withFinalNewline(editor.getMarkdown()) !== baseline.current;
      if (!dirty.current) callbacks.current.onChange?.(null);
    }
    callbacks.current.onRender?.();
    callbacks.current.onReady?.();
  }, [editor]);

  useEffect(() => {
    editor?.setEditable(editable, false);
  }, [editor, editable]);

  // The last keystrokes still count: an editor torn down leaves its edits behind.
  useEffect(() => () => flush());

  // New Markdown replaces the content once per frame; the whole document is
  // parsed, which is cheap for documents of the size the tools write.
  useEffect(() => {
    if (!editor || markdown === applied.current || dirty.current) return;
    const frame = requestAnimationFrame(() => {
      if (editor.isDestroyed || dirty.current) return;
      apply(editor, markdown);
      setRendered((count) => count + 1);
      callbacks.current.onRender?.();
    });
    return () => cancelAnimationFrame(frame);
  }, [editor, markdown]);

  useEffect(() => {
    if (!editor) return;
    const spans = highlight
      ? findPassageSpans(editor.state.doc, highlight.text, highlight.locator)
      : [];
    editor.commands.highlightPassage(spans);
    if (spans[0]) reveal(editor, spans[0].from);
  }, [editor, highlight, rendered]);

  // What this version changed against the one before it, over the text as
  // the file has it; the marks then follow the reader's edits.
  useEffect(() => {
    if (!editor) return;
    editor.commands.showChanges(
      previousMarkdown === null ? [] : changesBetween(previousMarkdown, markdown)
    );
  }, [editor, previousMarkdown, markdown, rendered]);

  useImperativeHandle(
    ref,
    () => ({
      getMarkdown: () => {
        flush();
        return editor ? withFinalNewline(editor.getMarkdown()) : markdown;
      },
      reset: () => {
        if (pending.current) clearTimeout(pending.current.timer);
        pending.current = null;
        dirty.current = false;
        if (!editor) return;
        apply(editor, markdown);
        setRendered((count) => count + 1);
      }
    }),
    [editor, markdown, flush]
  );

  function quote() {
    if (!editor || !onQuote) return;
    const { doc, selection } = editor.state;
    const { from, to } = selection;
    if (selection instanceof CellSelection) {
      // Cells dragged across in a table: quoted row by row, located by cell.
      const quoted = cellSelectionQuote(doc, selection);
      onQuote(quoted.text, quoted.locator);
    } else {
      onQuote(selectedText(doc, from, to), locateSelection(doc, from, to));
    }
    editor.view.dispatch(editor.state.tr.setSelection(TextSelection.create(doc, to)));
    document.getSelection()?.removeAllRanges();
  }

  return (
    <>
      {/* Positioned, so the quote action placed in it moves with the text when
          the panel scrolls, whatever is positioned outside the scroller. */}
      <EditorContent editor={editor} className="document-editor relative" />
      {editor && onQuote && (
        <BubbleMenu
          editor={editor}
          pluginKey="quoteMenu"
          updateDelay={150}
          shouldShow={({ state, from, to }) =>
            !state.selection.empty && state.doc.textBetween(from, to, "\n").trim().length > 0
          }
          options={MENU_OPTIONS}
          className="z-30"
          // Pressing the button must not take the selection it is about to quote.
          onMouseDown={(event) => event.preventDefault()}
        >
          <Button
            label={t("file_preview_quote_selection")}
            variant="primary"
            size="sm"
            elevation="med"
            icon={<TextQuote className="size-3.5" aria-hidden="true" />}
            onClick={quote}
          />
        </BubbleMenu>
      )}
    </>
  );
}
