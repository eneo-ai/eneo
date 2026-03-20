<script lang="ts">
  import type {
    FlowRunDebugRagReferenceChunk,
    Intric,
  } from "@intric/intric-js";
  import { Button, Dialog, Tooltip } from "@intric/ui";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { m } from "$lib/paraglide/messages";
  import { onDestroy, tick } from "svelte";
  import {
    createDocumentHighlighter,
    type FlowDocumentHighlighter,
  } from "$lib/features/flows/utils/document-highlighter";

  export let intric: Intric;
  export let infoBlobId: string;
  export let title: string | null = null;
  export let sourceIdShort: string | null = null;
  export let chunks: FlowRunDebugRagReferenceChunk[] = [];

  let isOpen: Dialog.OpenState;
  let loadingDocument = false;
  let loadError = false;
  let documentText = "";
  let sourceUrl: string | null = null;
  let textContainer: HTMLElement | null = null;
  let highlighter: FlowDocumentHighlighter | null = null;
  let activeChunkIndex: number | null = null;

  $: chunkItems = (chunks ?? [])
    .filter((chunk) => typeof chunk.snippet === "string" && chunk.snippet.trim().length > 0)
    .sort((a, b) => (a.chunk_no ?? 0) - (b.chunk_no ?? 0));
  $: allSnippets = chunkItems.map((chunk) => chunk.snippet);

  $: if ($isOpen && !loadingDocument && !documentText && !loadError) {
    void loadDocument();
  }

  $: if ($isOpen && !loadingDocument && !loadError && documentText && textContainer) {
    void applyHighlights();
  }

  $: if (!$isOpen) {
    activeChunkIndex = null;
    highlighter?.destroy();
    highlighter = null;
  }

  onDestroy(() => {
    highlighter?.destroy();
  });

  function cleanSourceDisplay(displayTitle: string | null, url: string | null): string {
    if (displayTitle && !displayTitle.startsWith("http")) return displayTitle;
    const urlStr = url || displayTitle;
    if (!urlStr) return "";
    try {
      const u = new URL(urlStr);
      const path = u.pathname.length > 30 ? u.pathname.slice(0, 27) + "..." : u.pathname;
      return u.hostname + (path === "/" ? "" : path);
    } catch {
      return urlStr.slice(0, 50);
    }
  }

  function scoreBadgeClass(score: number): string {
    if (score >= 0.5) return "bg-positive-dimmer text-positive-stronger";
    if (score >= 0.3) return "bg-warning-dimmer text-warning-stronger";
    return "bg-negative-dimmer text-negative-stronger";
  }

  function scoreLabel(score: number): string {
    if (score >= 0.5) return m.flow_run_knowledge_relevance_high();
    if (score >= 0.3) return m.flow_run_knowledge_relevance_moderate();
    return m.flow_run_knowledge_relevance_low();
  }

  async function loadDocument() {
    loadingDocument = true;
    loadError = false;
    try {
      const blob = await intric.infoBlobs.get({ id: infoBlobId });
      documentText = blob.text ?? "";
      sourceUrl = blob.metadata?.url ?? null;
    } catch (error) {
      console.error("Failed to load flow chunk viewer source", error);
      loadError = true;
    } finally {
      loadingDocument = false;
    }
  }

  async function applyHighlights() {
    await tick();
    if (!textContainer) return;

    highlighter?.destroy();
    highlighter = createDocumentHighlighter(textContainer);
    highlighter.highlight([{ group: "chunk-match", snippets: allSnippets }]);
    if (highlighter.getMatchCount("chunk-match") > 0) {
      highlighter.scrollToFirstMatch("chunk-match");
    }
    if (activeChunkIndex !== null) {
      activateChunk(activeChunkIndex);
    }
  }

  function activateChunk(index: number) {
    activeChunkIndex = index;
    const snippet = chunkItems[index]?.snippet;
    if (!snippet || !highlighter) return;
    highlighter.setActive(snippet);
  }

  function resetChunkHighlight() {
    activeChunkIndex = null;
    highlighter?.clearGroup("chunk-active");
  }

  function showViewer() {
    $isOpen = true;
  }

  function nextChunk() {
    if (!chunkItems.length) return;
    const next = activeChunkIndex === null ? 0 : (activeChunkIndex + 1) % chunkItems.length;
    activateChunk(next);
  }

  function previousChunk() {
    if (!chunkItems.length) return;
    const prev = activeChunkIndex === null
      ? chunkItems.length - 1
      : (activeChunkIndex - 1 + chunkItems.length) % chunkItems.length;
    activateChunk(prev);
  }
</script>

<svelte:options runes={false} />

<Dialog.Root bind:isOpen>
  {#if $$slots.default}
    <slot {showViewer}></slot>
  {/if}

  <Dialog.Content width="large">
    <Dialog.Title>
      {cleanSourceDisplay(title, sourceUrl) || m.flow_run_knowledge_untitled_source()}
    </Dialog.Title>
    <Dialog.Description hidden>{m.flow_run_knowledge_document_description()}</Dialog.Description>

    <Dialog.Section scrollable class="max-h-[68vh]">
      <div class="grid gap-4 p-4 lg:grid-cols-[minmax(230px,280px)_minmax(0,1fr)]">
        <aside class="space-y-3">
          <div class="rounded-md border border-default bg-hover-dimmer p-3">
            <div class="text-sm font-medium text-secondary">
              {cleanSourceDisplay(title, sourceUrl) || m.flow_run_knowledge_untitled_source()}
            </div>
            {#if sourceUrl && title && !title.startsWith("http")}
              <div class="mt-0.5 truncate font-mono text-[11px] text-muted">
                {cleanSourceDisplay(null, sourceUrl)}
              </div>
            {/if}
            <div class="mt-1.5 flex items-center gap-3">
              {#if sourceIdShort}
                <Tooltip text={infoBlobId}>
                  <span class="font-mono text-[11px] text-muted opacity-60">{sourceIdShort}</span>
                </Tooltip>
              {/if}
              {#if sourceUrl}
                <a
                  href={sourceUrl}
                  target="_blank"
                  rel="noreferrer"
                  class="text-[11px] font-medium text-accent-stronger hover:underline"
                >
                  {m.go_to_website()}
                </a>
              {/if}
            </div>
          </div>

          <div class="space-y-2">
            <div class="flex items-center justify-between">
              <h4 class="text-xs font-semibold text-muted">
                {m.flow_run_knowledge_segment_header({ count: String(chunkItems.length) })}
              </h4>
              {#if activeChunkIndex !== null}
                <button
                  class="rounded px-2 py-1 text-[11px] font-medium text-accent-stronger hover:bg-hover-default"
                  on:click={resetChunkHighlight}
                >
                  {m.clear()}
                </button>
              {/if}
            </div>
            {#if chunkItems.length === 0}
              <p class="rounded-md border border-default bg-primary p-2 text-xs text-muted">
                {m.flow_run_knowledge_no_snippets()}
              </p>
            {:else}
              <div class="max-h-[44vh] space-y-1.5 overflow-auto pr-1">
                {#each chunkItems as chunk, index (`${chunk.chunk_no ?? 0}-${index}`)}
                  <button
                    class="w-full rounded-md border border-default border-l-[3px] border-l-transparent px-2.5 py-2 text-left text-xs transition-colors hover:bg-hover-default"
                    class:bg-accent-dimmer={activeChunkIndex === index}
                    style:border-left-color={activeChunkIndex === index ? "var(--accent-default)" : undefined}
                    on:click={() => activateChunk(index)}
                  >
                    <div class="flex items-center justify-between gap-2">
                      <span class="font-semibold text-secondary">
                        {m.flow_run_knowledge_chunk_label({ chunk: String(chunk.chunk_no ?? 0) })}
                      </span>
                      <Tooltip text={Number(chunk.score ?? 0).toFixed(2)}>
                        <span class={["rounded-full px-1.5 py-0.5 text-[10px] font-medium", scoreBadgeClass(Number(chunk.score ?? 0))]}>
                          {scoreLabel(Number(chunk.score ?? 0))}
                        </span>
                      </Tooltip>
                    </div>
                    <p class="mt-1 line-clamp-3 text-[11px] leading-relaxed text-muted">{chunk.snippet}</p>
                  </button>
                {/each}
              </div>
            {/if}
          </div>
        </aside>

        <section class="rounded-md border border-default bg-primary">
          {#if loadingDocument}
            <div class="flex items-center gap-2 p-4 text-sm text-secondary">
              <IconLoadingSpinner class="size-4 animate-spin" />
              {m.flow_run_knowledge_loading_document()}
            </div>
          {:else if loadError}
            <p class="p-4 text-sm text-negative-default">
              {m.flow_run_knowledge_document_load_failed()}
            </p>
          {:else if !documentText}
            <p class="p-4 text-sm text-muted">{m.empty()}</p>
          {:else}
            <div
              bind:this={textContainer}
              class="knowledge-document h-[52vh] overflow-auto px-4 py-3"
              style="content-visibility: auto;"
            >
              <pre class="whitespace-pre-wrap break-words font-sans text-[15px] leading-relaxed">{documentText}</pre>
            </div>
            <div class="flex items-center justify-between border-t border-default bg-hover-dimmer px-4 py-2.5">
              <div class="inline-flex items-center gap-2 text-[11px] text-muted">
                <span class="legend-swatch"></span>
                <span>{m.flow_run_knowledge_highlight_legend()}</span>
              </div>
              <div class="inline-flex items-center gap-1">
                <Button variant="outlined" class="text-xs" on:click={previousChunk}>
                  {m.flow_run_knowledge_prev_match()}
                </Button>
                <span class="px-2 text-[11px] tabular-nums text-muted">
                  {#if activeChunkIndex !== null}
                    {m.flow_run_knowledge_chunk_position({ current: String(activeChunkIndex + 1), total: String(chunkItems.length) })}
                  {:else}
                    {m.flow_run_knowledge_chunk_count({ count: String(chunkItems.length) })}
                  {/if}
                </span>
                <Button variant="outlined" class="text-xs" on:click={nextChunk}>
                  {m.flow_run_knowledge_next_match()}
                </Button>
              </div>
            </div>
          {/if}
        </section>
      </div>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button variant="primary" is={close}>{m.done()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<style>
  :global(::highlight(chunk-match)) {
    background-color: color-mix(in srgb, var(--warning-stronger) 30%, transparent);
  }

  :global(::highlight(chunk-active)) {
    background-color: color-mix(in srgb, var(--warning-stronger) 50%, transparent);
    text-decoration: underline;
    text-decoration-color: color-mix(in srgb, var(--warning-stronger) 70%, transparent);
    text-decoration-thickness: 2px;
    text-decoration-skip-ink: none;
    text-underline-offset: 4px;
  }

  :global(.knowledge-document .flow-highlight) {
    border-radius: 2px;
    padding: 0 1px;
    background-color: color-mix(in srgb, var(--warning-stronger) 30%, transparent);
  }

  :global(.knowledge-document .flow-highlight--chunk-active) {
    background-color: color-mix(in srgb, var(--warning-stronger) 50%, transparent);
    box-shadow: inset 0 -2px 0 color-mix(in srgb, var(--warning-stronger) 70%, transparent);
  }

  .legend-swatch {
    display: inline-block;
    height: 12px;
    width: 18px;
    border-radius: 3px;
    border: 1px solid color-mix(in srgb, var(--warning-stronger) 50%, transparent);
    background-color: color-mix(in srgb, var(--warning-stronger) 30%, transparent);
  }
</style>
