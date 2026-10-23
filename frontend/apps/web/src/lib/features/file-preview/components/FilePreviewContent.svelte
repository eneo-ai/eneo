<script lang="ts">
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import { tick } from "svelte";
  import type { PreviewPassage } from "../FilePreview.svelte";
  import TextQuote from "@lucide/svelte/icons/text-quote";
  import type { PreviewContent } from "../loadPreview";
  import {
    findPassage,
    locatePassage,
    locatorSheet,
    markPassages,
    watchSelection,
    type SelectedPassage
  } from "../selection";
  import DocumentEditor from "./DocumentEditor.svelte";
  import DocxPreview from "./DocxPreview.svelte";
  import PdfPreview from "./PdfPreview.svelte";
  import TablePreview from "./TablePreview.svelte";

  type Props = {
    content: PreviewContent;
    onready?: () => void;
    onerror?: () => void;
    title: string;
    /** A passage to mark in the content and scroll to, such as a quote sent earlier. */
    highlight: PreviewPassage | null;
    /** Called with the selected text, and where it stands, when the user quotes it. */
    onquote: (text: string, locator: string | null) => void;
    /** Whether a Markdown document may be edited in place. */
    editable?: boolean;
    /** The reader's unsaved text of a Markdown document, shown in place of the file's. */
    edits?: string | null;
    /** The version before this one, as Markdown; what changed against it is marked. */
    previousMarkdown?: string | null;
    /** The document's text as the reader has it; null once it is the file's again. */
    onchange?: (text: string | null) => void;
    /** The reader asked to save the document (Mod+S). */
    onsave?: () => void;
  };

  let {
    content,
    title,
    highlight,
    onquote,
    onready,
    onerror,
    editable = false,
    edits = null,
    previousMarkdown = null,
    onchange,
    onsave
  }: Props = $props();

  let editor = $state<DocumentEditor>();

  /** The document as the reader has it now; null unless a Markdown document is shown. */
  export function getMarkdown(): string | null {
    return editor?.getMarkdown() ?? null;
  }

  /** Drops the reader's edits to the document on show. */
  export function resetEditor() {
    editor?.reset();
  }

  // A Word document and the editor report readiness themselves.
  $effect(() => {
    if (content.kind === "docx" || content.kind === "pdf" || content.kind === "markdown") return;
    const ready = onready;
    let active = true;
    void tick().then(() => {
      if (active) ready?.();
    });
    return () => {
      active = false;
    };
  });

  let body = $state<HTMLElement>();
  let bodyWidth = $state(0);
  let bodyHeight = $state(0);
  let docx = $state<DocxPreview>();

  /** A selection and where it is, measured from the preview's top left corner. */
  type Placed = { text: string; range: Range; centre: number; top: number; bottom: number };

  // A Word document lives in a frame with a selection of its own; a plain text
  // file draws into the page, whose selection counts while it lies wholly
  // inside the preview. A Markdown document's editor places its own quote
  // action; a PDF's text belongs to the browser's viewer and can be reached by
  // none of these.
  let frameSelection = $state.raw<Placed | null>(null);
  let pageSelection = $state.raw<Placed | null>(null);
  const selection = $derived(frameSelection ?? pageSelection);

  function place(passage: SelectedPassage | null): Placed | null {
    if (!passage || !body) return null;
    const box = body.getBoundingClientRect();
    const top = passage.rect.top - box.top;
    const bottom = passage.rect.bottom - box.top;
    // Scrolled out of sight: nothing to attach to.
    if (bottom < 0 || top > box.height) return null;
    return {
      text: passage.text,
      range: passage.range,
      centre: (passage.rect.left + passage.rect.right) / 2 - box.left,
      top,
      bottom
    };
  }

  $effect(() => {
    if (!body || content.kind !== "text") return;
    const watch = watchSelection(document, {
      within: () => body,
      report: (passage) => (pageSelection = place(passage))
    });
    // Resizing the panel moves the selection without scrolling anything.
    const observer = new ResizeObserver(watch.refresh);
    observer.observe(body);
    return () => {
      observer.disconnect();
      watch.stop();
    };
  });

  // The quote action hangs on the selection: above it, or below when there is
  // no room above, and never outside the preview.
  const GAP = 8;
  let popupWidth = $state(0);
  let popupHeight = $state(0);
  const popupPosition = $derived.by(() => {
    if (!selection) return null;
    const above = selection.top - GAP - popupHeight;
    const top =
      above >= GAP
        ? above
        : Math.max(GAP, Math.min(selection.bottom + GAP, bodyHeight - popupHeight - GAP));
    const left = Math.max(
      GAP,
      Math.min(selection.centre - popupWidth / 2, bodyWidth - popupWidth - GAP)
    );
    return { top, left };
  });

  function quote() {
    if (!selection || !body) return;
    const { range, text } = selection;
    // A Word document's selection lies in its frame's document, not the page.
    const owner = range.startContainer.ownerDocument;
    const root = owner === document ? body : owner?.body;
    onquote(text, root ? locatePassage(root, range, text) : null);
    docx?.clearSelection();
    if (pageSelection) document.getSelection()?.removeAllRanges();
  }

  // Marks the highlighted passage in text drawn into the page; a Word
  // document marks its own frame, and the editor its document.
  $effect(() => {
    const passage = highlight;
    const root = body;
    if (!root || content.kind !== "text") return;
    let current = true;
    // After the table has switched to the sheet the passage is on.
    void tick().then(() => {
      if (!current) return;
      markPassages(document, passage ? findPassage(root, passage.text, passage.locator) : []);
    });
    return () => {
      current = false;
      markPassages(document, []);
    };
  });
</script>

<div
  bind:this={body}
  bind:clientWidth={bodyWidth}
  bind:clientHeight={bodyHeight}
  class="relative flex min-h-0 flex-1 flex-col"
>
  {#if content.kind === "docx"}
    <DocxPreview
      bind:this={docx}
      {onready}
      {onerror}
      bytes={content.bytes}
      {title}
      {highlight}
      onselection={(passage) => (frameSelection = place(passage))}
    />
  {:else if content.kind === "pdf"}
    <PdfPreview blob={content.blob} {title} {onready} {onerror} />
  {:else if content.kind === "table"}
    <TablePreview
      sheets={content.sheets}
      sheet={locatorSheet(highlight?.locator ?? null)}
      {highlight}
      {onquote}
    />
  {:else}
    <div class="min-h-0 flex-1 overflow-auto">
      {#if content.kind === "markdown"}
        <DocumentEditor
          bind:this={editor}
          markdown={content.text}
          {edits}
          {editable}
          {highlight}
          {previousMarkdown}
          {onquote}
          {onchange}
          {onsave}
          {onready}
        />
      {:else}
        <pre class="p-6 font-mono text-sm break-words whitespace-pre-wrap">{content.text}</pre>
      {/if}
    </div>
    {#if content.truncated}
      <p class="text-muted-foreground border-border shrink-0 border-t px-4 py-2 text-xs">
        {m.file_preview_text_truncated()}
      </p>
    {/if}
  {/if}

  {#if selection && popupPosition}
    <div
      bind:offsetWidth={popupWidth}
      bind:offsetHeight={popupHeight}
      class="absolute z-30"
      style:top="{popupPosition.top}px"
      style:left="{popupPosition.left}px"
    >
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
    </div>
  {/if}
</div>

<style>
  /* The mark painted by markPassages (../selection.ts) on text drawn into the page. */
  :global(::highlight(file-preview-quote)) {
    background-color: var(--warning-dimmer);
  }
</style>
