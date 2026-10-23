<script lang="ts">
  import { Editor } from "@tiptap/core";
  import { BubbleMenu } from "@tiptap/extension-bubble-menu";
  import { TextSelection } from "@tiptap/pm/state";
  import { CellSelection } from "@tiptap/pm/tables";
  import TextQuote from "@lucide/svelte/icons/text-quote";
  import { tick, untrack } from "svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { getAttachmentUrlService } from "$lib/features/attachments/AttachmentUrlService.svelte";
  import { m } from "$lib/paraglide/messages";
  import type { PreviewPassage } from "../FilePreview.svelte";
  import { changesBetween } from "../editor/changes";
  import { replaceContent } from "../editor/content";
  import { documentExtensions, withFinalNewline } from "../editor/extensions";
  import {
    cellSelectionQuote,
    findPassageSpans,
    locateSelection,
    selectedText
  } from "../editor/passages";

  type Props = {
    /** The document as Markdown. A change replaces the content unless the reader has unsaved edits. */
    markdown: string;
    /**
     * The reader's unsaved text of the document, left by an editor that was
     * torn down: shown in place of `markdown`, and still unsaved.
     */
    edits?: string | null;
    editable?: boolean;
    /** A passage to mark and scroll to; null clears the mark. */
    highlight?: PreviewPassage | null;
    /** The version before this one, as Markdown; what changed against it is marked. */
    previousMarkdown?: string | null;
    /** Called with the selected text, and where it stands, when the reader quotes it. */
    onquote?: (text: string, locator: string | null) => void;
    /**
     * The document's text as the reader has it, whenever they change it, and
     * null once it is `markdown` again. Never called for a `markdown` update,
     * nor for the editor's own tidying of a loaded document.
     */
    onchange?: (text: string | null) => void;
    /** The reader asked to save (Mod+S) while editing. */
    onsave?: () => void;
    /** Each `markdown` value has been laid out. */
    onrender?: () => void;
    /** The first content has been laid out. */
    onready?: () => void;
  };

  let {
    markdown,
    edits = null,
    editable = false,
    highlight = null,
    previousMarkdown = null,
    onquote,
    onchange,
    onsave,
    onrender,
    onready
  }: Props = $props();

  const urls = getAttachmentUrlService();

  let mount = $state<HTMLDivElement>();
  let menu = $state<HTMLDivElement>();
  let editor: Editor | undefined;
  // The reader's edits win over a `markdown` update until they are saved or dropped.
  let dirty = false;
  // The Markdown the editor last took, so the same text is not parsed again.
  let applied: string | null = null;
  // The document as loaded, serialised: what the reader's text is compared
  // with. The file's own Markdown does not serve, since a document does not
  // come back byte for byte (a table's columns are padded, for one).
  let baseline = "";
  // Content is being put in place; the editor's own tidying of it is no edit.
  let applying = false;
  let frame = 0;
  // Bumped when the document changed under the highlight, so it is placed again.
  let rendered = $state(0);
  // Once the document is marked edited, a further keystroke is marked this
  // long after the last, since marking serialises the whole document.
  const EDIT_DELAY = 150;
  let pending = 0;

  /** Compares the reader's text with the document as loaded, and tells of a difference. */
  function noteEdit(current: Editor) {
    pending = 0;
    const text = withFinalNewline(current.getMarkdown());
    const changed = text !== baseline;
    if (!changed && !dirty) return;
    dirty = changed;
    onchange?.(changed ? text : null);
  }

  /** Marks an edit that is still waiting, so whatever reads the mark reads it current. */
  function flush() {
    if (!pending) return;
    clearTimeout(pending);
    if (editor && !editor.isDestroyed) noteEdit(editor);
    else pending = 0;
  }

  $effect(() => {
    const element = mount;
    const menuElement = menu;
    if (!element || !menuElement) return;
    const initial = untrack(() => markdown);
    const created = new Editor({
      element,
      extensions: [
        ...documentExtensions({
          resolveImage: (fileId) => urls.resolveUrl({ id: fileId }),
          pageBreakLabel: m.file_preview_page_break()
        }),
        // The quote action floats over the selection, read-only or not.
        BubbleMenu.configure({
          element: menuElement,
          pluginKey: "quoteMenu",
          updateDelay: 150,
          shouldShow: ({ state, from, to }) =>
            !!onquote &&
            !state.selection.empty &&
            state.doc.textBetween(from, to, "\n").trim().length > 0,
          // Positioned within the editor, so it scrolls with the text and
          // no transformed ancestor of the panel can throw it off.
          options: {
            strategy: "absolute",
            placement: "top",
            offset: 8,
            flip: true,
            shift: { padding: 8 }
          }
        })
      ],
      content: initial,
      contentType: "markdown",
      editable: untrack(() => editable),
      editorProps: {
        attributes: {
          class: "prose mx-auto max-w-[72ch] p-6 text-base break-words outline-none"
        },
        handleKeyDown: (_view, event) => {
          if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
            event.preventDefault();
            flush();
            onsave?.();
            return true;
          }
          return false;
        }
      }
    });
    // A keystroke only marks the document edited; nothing is saved here. The
    // mark compares text with the document as loaded, since the editor also
    // tidies a loaded document (a paragraph to type in after a final code
    // block) without changing what it says, and a reader cannot edit a
    // document that is read-only. The first keystroke is marked at once, so
    // whatever guards unsaved edits sees them; a burst that follows is marked
    // once, a moment after its last.
    created.on("update", () => {
      if (applying || !created.isEditable) return;
      clearTimeout(pending);
      if (!dirty) noteEdit(created);
      else pending = window.setTimeout(() => noteEdit(created), EDIT_DELAY);
    });
    editor = created;
    applied = initial;
    baseline = withFinalNewline(created.getMarkdown());
    // Edits left by an earlier editor of this document take the place of the
    // loaded text, compared with it as before.
    const left = untrack(() => edits);
    if (left !== null) {
      applying = true;
      try {
        replaceContent(created, left);
      } finally {
        applying = false;
      }
      dirty = withFinalNewline(created.getMarkdown()) !== baseline;
      if (!dirty) onchange?.(null);
    }
    let active = true;
    void tick().then(() => {
      if (!active) return;
      rendered++;
      onrender?.();
      onready?.();
    });
    return () => {
      active = false;
      cancelAnimationFrame(frame);
      // The last keystrokes still count: an editor torn down leaves its edits behind.
      flush();
      created.destroy();
      editor = undefined;
    };
  });

  $effect(() => {
    const on = editable;
    editor?.setEditable(on, false);
  });

  // New Markdown (a streaming draft grows, another version opens) replaces the
  // content once per frame; the whole document is parsed, which is cheap for
  // documents of the size the tools write.
  $effect(() => {
    const next = markdown;
    if (!editor || next === applied || dirty) return;
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      if (!editor || editor.isDestroyed || dirty) return;
      apply(editor, next);
      rendered++;
      onrender?.();
    });
  });

  $effect(() => {
    const passage = highlight;
    void rendered;
    const current = editor;
    if (!current) return;
    const spans = passage ? findPassageSpans(current.state.doc, passage.text, passage.locator) : [];
    current.commands.highlightPassage(spans);
    if (spans.length > 0) reveal(current, spans[0].from);
  });

  // What this version changed against the one before it, over the text as
  // the file has it; the marks then follow the reader's edits.
  $effect(() => {
    const previous = previousMarkdown;
    const current = markdown;
    void rendered;
    if (!editor) return;
    editor.commands.showChanges(previous === null ? [] : changesBetween(previous, current));
  });

  /** Scrolls whatever scrolls the editor to centre the position. */
  function reveal(current: Editor, pos: number) {
    let scroller = current.view.dom.parentElement;
    while (scroller) {
      const style = getComputedStyle(scroller);
      if (/auto|scroll/.test(style.overflowY) && scroller.scrollHeight > scroller.clientHeight) {
        break;
      }
      scroller = scroller.parentElement;
    }
    if (!scroller) return;
    const coords = current.view.coordsAtPos(pos);
    const frameRect = scroller.getBoundingClientRect();
    scroller.scrollBy({
      top: (coords.top + coords.bottom) / 2 - (frameRect.top + frameRect.height / 2)
    });
  }

  function quote() {
    if (!editor || !onquote) return;
    const { doc, selection } = editor.state;
    const { from, to } = selection;
    if (selection instanceof CellSelection) {
      // Cells dragged across in a table: quoted row by row, located by cell.
      const quoted = cellSelectionQuote(doc, selection);
      onquote(quoted.text, quoted.locator);
    } else {
      onquote(selectedText(doc, from, to), locateSelection(doc, from, to));
    }
    editor.view.dispatch(editor.state.tr.setSelection(TextSelection.create(doc, to)));
    document.getSelection()?.removeAllRanges();
  }

  /** The document as the reader has it now. */
  export function getMarkdown(): string {
    flush();
    return editor ? withFinalNewline(editor.getMarkdown()) : markdown;
  }

  /** Puts `next` in the editor as the document the reader's text is compared with. */
  function apply(current: Editor, next: string) {
    applying = true;
    try {
      replaceContent(current, next);
    } finally {
      applying = false;
    }
    applied = next;
    baseline = withFinalNewline(current.getMarkdown());
  }

  /** Drops the reader's edits and shows the file's text again. */
  export function reset() {
    clearTimeout(pending);
    pending = 0;
    dirty = false;
    if (!editor) return;
    apply(editor, markdown);
    rendered++;
  }
</script>

<!-- Positioned, so the quote action placed in it moves with the text when the
     panel scrolls, whatever is positioned outside the scroller. -->
<div bind:this={mount} class="document-editor relative"></div>
<!-- Placed by the editor over the selection; hidden until there is one. -->
<div bind:this={menu} class="z-30" style:visibility="hidden">
  {#if onquote}
    <!-- Pressing the button must not take the selection it is about to quote. -->
    <Button
      size="sm"
      class="shadow-lg"
      onmousedown={(event: MouseEvent) => event.preventDefault()}
      onclick={quote}
    >
      <TextQuote data-icon="inline-start" aria-hidden="true" />
      {m.file_preview_quote_selection()}
    </Button>
  {/if}
</div>

<style>
  .document-editor :global(.passage-highlight) {
    background-color: var(--warning-dimmer);
  }

  /* The dimmer tokens are too faint for a mark inside running text; the
     default tones mixed down read in both themes. Added text is also
     underlined, so the change shows without its colour. */
  .document-editor :global(.change-added) {
    background-color: color-mix(in oklab, var(--positive-default) 28%, transparent);
    border-radius: 0.15em;
    text-decoration: underline;
    text-decoration-color: var(--positive-default);
    text-decoration-thickness: 2px;
    text-underline-offset: 0.15em;
  }

  /* Not part of the text: a selection over it must not seem to take it. */
  .document-editor :global(.change-removed) {
    user-select: none;
    margin-right: 0.25em;
    background-color: color-mix(in oklab, var(--negative-default) 22%, transparent);
    border-radius: 0.15em;
    color: var(--color-muted-foreground);
    text-decoration: line-through;
  }

  .document-editor :global(.page-break) {
    position: relative;
    margin: 1.5rem 0;
    border-top: 1px dashed var(--color-border);
    text-align: center;
  }

  .document-editor :global(.page-break::after) {
    content: attr(aria-label);
    position: relative;
    top: -0.75em;
    padding: 0 0.5em;
    background-color: var(--color-background);
    color: var(--color-muted-foreground);
    font-size: 0.75rem;
  }

  .document-editor :global(ul[data-type="taskList"]) {
    padding-left: 0;
    list-style: none;
  }

  .document-editor :global(ul[data-type="taskList"] > li) {
    display: flex;
    gap: 0.5em;
    align-items: flex-start;
  }

  /* The box sits on the first line of its text; the text block drops the
     block margins the prose styles give a div. */
  .document-editor :global(ul[data-type="taskList"] > li > label) {
    display: flex;
    flex: none;
    align-items: center;
    height: 1lh;
  }

  .document-editor :global(ul[data-type="taskList"] > li > div) {
    flex: 1;
    margin: 0;
  }

  /* Code keeps the chat's dark block, so its text must be light in both themes. */
  .document-editor :global(pre) {
    color: var(--text-color-on-fill);
    color-scheme: dark;
  }

  .document-editor :global(.eneo-figure) {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    align-items: center;
  }

  .document-editor :global(.eneo-figure img) {
    max-width: 100%;
    margin: 0;
  }

  .document-editor :global(.eneo-figure-caption) {
    color: var(--color-muted-foreground);
    font-size: 0.875em;
    font-style: italic;
    text-align: center;
  }

  .document-editor :global(table) {
    border-collapse: collapse;
  }

  .document-editor :global(.selectedCell) {
    background-color: var(--accent-dimmer);
  }

  .document-editor :global(.ProseMirror-selectednode) {
    outline: 2px solid var(--accent-default);
  }
</style>
