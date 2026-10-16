<script lang="ts">
  import { Editor } from "@tiptap/core";
  import { BubbleMenu } from "@tiptap/extension-bubble-menu";
  import { TextSelection } from "@tiptap/pm/state";
  import TextQuote from "@lucide/svelte/icons/text-quote";
  import { tick, untrack } from "svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { getAttachmentUrlService } from "$lib/features/attachments/AttachmentUrlService.svelte";
  import { m } from "$lib/paraglide/messages";
  import type { PreviewPassage } from "../FilePreview.svelte";
  import { documentExtensions, withFinalNewline } from "../editor/extensions";
  import { findPassageSpans, locateSelection, selectedText } from "../editor/passages";

  type Props = {
    /** The document as Markdown. A change replaces the content unless the reader has unsaved edits. */
    markdown: string;
    editable?: boolean;
    /** A passage to mark and scroll to; null clears the mark. */
    highlight?: PreviewPassage | null;
    /** Called with the selected text, and where it stands, when the reader quotes it. */
    onquote?: (text: string, locator: string | null) => void;
    /** The reader changed the content; never called for a `markdown` update. */
    ondirty?: () => void;
    /** The reader asked to save (Mod+S) while editing. */
    onsave?: () => void;
    /** Each `markdown` value has been laid out. */
    onrender?: () => void;
    /** The first content has been laid out. */
    onready?: () => void;
  };

  let {
    markdown,
    editable = false,
    highlight = null,
    onquote,
    ondirty,
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
  let frame = 0;
  // Bumped when the document changed under the highlight, so it is placed again.
  let rendered = $state(0);

  const CONTENT = { contentType: "markdown", emitUpdate: false } as const;

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
      injectCSS: false,
      editorProps: {
        attributes: {
          class: "prose mx-auto max-w-[72ch] p-6 text-base break-words outline-none"
        },
        handleKeyDown: (_view, event) => {
          if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
            event.preventDefault();
            onsave?.();
            return true;
          }
          return false;
        }
      }
    });
    // A keystroke only marks the document edited; nothing is saved here.
    created.on("update", () => {
      dirty = true;
      ondirty?.();
    });
    editor = created;
    applied = initial;
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
      editor.commands.setContent(next, CONTENT);
      applied = next;
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
    onquote(selectedText(doc, from, to), locateSelection(doc, from, to));
    editor.view.dispatch(editor.state.tr.setSelection(TextSelection.create(doc, to)));
    document.getSelection()?.removeAllRanges();
  }

  /** The document as the reader has it now. */
  export function getMarkdown(): string {
    return editor ? withFinalNewline(editor.getMarkdown()) : markdown;
  }

  /** Drops the reader's edits and shows the file's text again. */
  export function reset() {
    dirty = false;
    if (!editor) return;
    editor.commands.setContent(markdown, CONTENT);
    applied = markdown;
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
