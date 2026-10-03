<script lang="ts">
  import { sanitizeLinkHref } from "$lib/components/markdown/index.js";
  import { m } from "$lib/paraglide/messages";
  import { onDestroy } from "svelte";
  import type { PreviewPassage } from "../FilePreview.svelte";
  import {
    findPassage,
    highlightRule,
    markPassages,
    watchSelection,
    type SelectedPassage
  } from "../selection";

  type Props = {
    bytes: ArrayBuffer;
    onready?: () => void;
    onerror?: () => void;
    title: string;
    /** A passage to mark in the document and scroll to. */
    highlight?: PreviewPassage | null;
    /** Reports the settled selection in the document, placed in the page's viewport. */
    onselection?: (passage: SelectedPassage | null) => void;
  };

  let { bytes, title, highlight = null, onselection, onready, onerror }: Props = $props();

  /** Drops the selection in the document, as after it has been quoted. */
  export function clearSelection() {
    frame?.contentDocument?.getSelection()?.removeAllRanges();
  }

  let frame = $state<HTMLIFrameElement>();
  let status = $state<"rendering" | "ready" | "failed">("rendering");

  // The document is laid out in a frame of its own: Word styles and the app's
  // styles cannot reach each other, and the sandbox (no allow-scripts) keeps
  // anything a document carries from running. Same-origin so the page can build
  // the frame's content; popups so a link opens in a new tab.
  const SANDBOX = "allow-same-origin allow-popups allow-popups-to-escape-sandbox";
  const SHELL = '<!doctype html><html><head><meta charset="utf-8"></head><body></body></html>';
  const PAGE_GUTTER = 16;
  // The pages are white paper in either theme; the frame's own document has no
  // theme tokens, so their shadow is a plain translucent black.
  /* eslint-disable eneo/no-raw-color */
  const FRAME_STYLE = `
    body { margin: 0; }
    .docx-wrapper { background: transparent; padding: ${PAGE_GUTTER}px; }
    .docx-wrapper > section.docx { margin-bottom: ${PAGE_GUTTER}px; box-shadow: 0 1px 4px rgb(0 0 0 / 0.25); }
    ${highlightRule("rgb(255 221 87 / 0.7)")}
  `;
  /* eslint-enable eneo/no-raw-color */

  // Width of a page as Word laid it out, measured once before any scaling.
  let pageWidth = 0;

  /** Scales the pages down to the panel's width; never up. */
  function fit() {
    const wrapper = frame?.contentDocument?.querySelector<HTMLElement>(".docx-wrapper");
    if (!frame || !wrapper || pageWidth === 0) return;
    const scale = Math.min(1, frame.clientWidth / (pageWidth + 2 * PAGE_GUTTER));
    wrapper.style.zoom = String(scale);
    // Scaling moved whatever is selected.
    selectionWatch?.refresh();
  }

  let selectionWatch: ReturnType<typeof watchSelection> | undefined;
  onDestroy(() => selectionWatch?.stop());

  async function render() {
    const frameDocument = frame?.contentDocument;
    if (!frameDocument) return;
    try {
      const { parseAsync, renderDocument } = await import("docx-preview");
      // Images inline as data URLs: object URLs would outlive the preview.
      const options = { inWrapper: true, useBase64URL: true };
      const nodes = await renderDocument(await parseAsync(bytes, options), options);
      if (!frame?.isConnected) return;

      for (const node of nodes) {
        (node.nodeName === "STYLE" ? frameDocument.head : frameDocument.body).appendChild(node);
      }
      // Last, so it overrides the renderer's own wrapper styles.
      const style = frameDocument.createElement("style");
      style.textContent = FRAME_STYLE;
      frameDocument.head.append(style);
      // The backdrop behind the pages follows the app's theme. It is copied in:
      // the frame keeps the light colour scheme its paper needs, and a frame
      // whose scheme differs from the page's is never transparent.
      frameDocument.documentElement.style.background = getComputedStyle(
        frame.parentElement!
      ).backgroundColor;
      for (const link of frameDocument.querySelectorAll("a")) {
        const href = sanitizeLinkHref(link.getAttribute("href"));
        if (!href) link.removeAttribute("href");
        else if (!href.startsWith("#")) {
          link.target = "_blank";
          link.rel = "noopener noreferrer";
        }
      }
      // The frame's document has a selection of its own, which the page reads
      // here; the frame's place in the page turns its coordinates into the page's.
      selectionWatch = watchSelection(frameDocument, {
        origin: () => {
          const box = frame!.getBoundingClientRect();
          return { x: box.left, y: box.top };
        },
        report: (passage) => onselection?.(passage)
      });
      pageWidth = frameDocument.querySelector<HTMLElement>("section.docx")?.offsetWidth ?? 0;
      fit();
      status = "ready";
      onready?.();
    } catch {
      status = "failed";
      onerror?.();
    }
  }

  $effect(() => {
    const passage = highlight;
    const frameDocument = frame?.contentDocument;
    if (status !== "ready" || !frameDocument) return;
    markPassages(
      frameDocument,
      passage ? findPassage(frameDocument.body, passage.text, passage.locator) : []
    );
  });

  $effect(() => {
    if (!frame) return;
    const observer = new ResizeObserver(fit);
    observer.observe(frame);
    return () => observer.disconnect();
  });
</script>

<div class="bg-muted relative min-h-0 flex-1">
  {#if status === "failed"}
    <p class="text-muted-foreground p-6 text-sm">{m.file_preview_failed()}</p>
  {:else}
    <iframe
      bind:this={frame}
      {title}
      sandbox={SANDBOX}
      srcdoc={SHELL}
      onload={render}
      class="absolute inset-0 h-full w-full border-0 {status === 'ready' ? '' : 'invisible'}"
    ></iframe>
    {#if status === "rendering"}
      <p class="text-muted-foreground absolute inset-0 p-6 text-sm" role="status">
        {m.file_preview_loading()}
      </p>
    {/if}
  {/if}
</div>
