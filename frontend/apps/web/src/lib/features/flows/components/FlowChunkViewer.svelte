<script lang="ts">
  import type { FlowRunDebugRagReferenceChunk, Eneo } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import { m } from "$lib/paraglide/messages";
  import { tick, type Snippet } from "svelte";
  import {
    createDocumentHighlighter,
    type FlowDocumentHighlighter
  } from "$lib/features/flows/utils/document-highlighter";
  import {
    getDisplayableKnowledgeChunks,
    normalizeKnowledgeMatchedCount
  } from "./flowRunKnowledgeTrace";
  import {
    formatKnowledgeSourceLabel,
    getKnowledgeRelevanceBadgeClass,
    getKnowledgeRelevanceLevel
  } from "./flowRunKnowledgePresentation";

  let {
    eneo,
    infoBlobId,
    title = null,
    sourceIdShort = null,
    chunks = [],
    matchedChunkCount = null,
    children
  }: {
    eneo: Eneo;
    infoBlobId: string;
    title?: string | null;
    sourceIdShort?: string | null;
    chunks?: FlowRunDebugRagReferenceChunk[];
    matchedChunkCount?: number | null;
    children?: Snippet<[{ showViewer: () => void }]>;
  } = $props();

  let isOpen = $state(false);
  let loadingDocument = $state(false);
  let loadError = $state(false);
  let documentText = $state("");
  let sourceUrl: string | null = $state(null);
  let textContainer: HTMLElement | null = $state(null);
  let highlighter: FlowDocumentHighlighter | null = $state(null);
  let activeChunkIndex: number | null = $state(null);

  let chunkItems = $derived(
    getDisplayableKnowledgeChunks(chunks).sort((a, b) => (a.chunk_no ?? 0) - (b.chunk_no ?? 0))
  );
  let allSnippets = $derived(chunkItems.map((chunk) => chunk.snippet));
  let totalMatchedChunkCount = $derived(
    normalizeKnowledgeMatchedCount(matchedChunkCount, chunkItems.length)
  );
  let hasHiddenMatchedChunks = $derived(totalMatchedChunkCount > chunkItems.length);

  $effect(() => {
    if (isOpen && !loadingDocument && !documentText && !loadError) {
      void loadDocument();
    }
  });

  $effect(() => {
    if (isOpen && !loadingDocument && !loadError && documentText && textContainer) {
      void applyHighlights();
    }
  });

  $effect(() => {
    if (!isOpen) {
      activeChunkIndex = null;
      highlighter?.destroy();
      highlighter = null;
    }
  });

  $effect(() => {
    return () => {
      highlighter?.destroy();
    };
  });

  function scoreLabel(score: number): string {
    switch (getKnowledgeRelevanceLevel(score)) {
      case "high":
        return m.flow_run_knowledge_relevance_high();
      case "moderate":
        return m.flow_run_knowledge_relevance_moderate();
      case "low":
        return m.flow_run_knowledge_relevance_low();
    }
  }

  async function loadDocument() {
    loadingDocument = true;
    loadError = false;
    try {
      const blob = await eneo.infoBlobs.get({ id: infoBlobId });
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
    isOpen = true;
  }

  function nextChunk() {
    if (!chunkItems.length) return;
    const next = activeChunkIndex === null ? 0 : (activeChunkIndex + 1) % chunkItems.length;
    activateChunk(next);
  }

  function previousChunk() {
    if (!chunkItems.length) return;
    const prev =
      activeChunkIndex === null
        ? chunkItems.length - 1
        : (activeChunkIndex - 1 + chunkItems.length) % chunkItems.length;
    activateChunk(prev);
  }

  function openSourceUrl() {
    if (!sourceUrl) return;
    window.open(sourceUrl, "_blank", "noopener,noreferrer");
  }
</script>

<Dialog.Root bind:open={isOpen}>
  {#if children}
    {@render children({ showViewer })}
  {/if}

  <Dialog.Content class="!max-w-5xl" showCloseButton={false}>
    <Dialog.Header>
      <Dialog.Title>
        {formatKnowledgeSourceLabel(title, sourceUrl, {
          maxPathLength: 30,
          maxFallbackLength: 50
        }) || m.flow_run_knowledge_untitled_source()}
      </Dialog.Title>
      <Dialog.Description class="sr-only"
        >{m.flow_run_knowledge_document_description()}</Dialog.Description
      >
    </Dialog.Header>

    <div class="max-h-[68vh] overflow-y-auto">
      <div class="grid gap-4 p-4 lg:grid-cols-[minmax(230px,280px)_minmax(0,1fr)]">
        <aside class="flex flex-col gap-3">
          <div class="border-default border-b pb-3">
            <div class="text-secondary text-sm font-medium">
              {formatKnowledgeSourceLabel(title, sourceUrl, {
                maxPathLength: 30,
                maxFallbackLength: 50
              }) || m.flow_run_knowledge_untitled_source()}
            </div>
            {#if sourceUrl && title && !title.startsWith("http")}
              <div class="text-muted mt-0.5 truncate font-mono text-xs">
                {formatKnowledgeSourceLabel(null, sourceUrl, {
                  maxPathLength: 30,
                  maxFallbackLength: 50
                })}
              </div>
            {/if}
            <div class="mt-1.5 flex items-center gap-3">
              {#if sourceIdShort}
                <Tooltip.Provider delayDuration={150}>
                  <Tooltip.Root>
                    <Tooltip.Trigger>
                      <span class="text-muted font-mono text-xs opacity-60">{sourceIdShort}</span>
                    </Tooltip.Trigger>
                    <Tooltip.Content>{infoBlobId}</Tooltip.Content>
                  </Tooltip.Root>
                </Tooltip.Provider>
              {/if}
              {#if sourceUrl}
                <button
                  type="button"
                  class="text-accent-stronger text-xs font-medium hover:underline"
                  onclick={openSourceUrl}
                >
                  {m.go_to_website()}
                </button>
              {/if}
            </div>
          </div>

          <div class="flex flex-col gap-2">
            <div class="flex items-center justify-between">
              <h4 class="text-muted text-xs font-semibold">
                {#if hasHiddenMatchedChunks}
                  {m.flow_run_knowledge_segment_header_displayed({
                    displayed: String(chunkItems.length),
                    matched: String(totalMatchedChunkCount)
                  })}
                {:else}
                  {m.flow_run_knowledge_segment_header({ count: String(chunkItems.length) })}
                {/if}
              </h4>
              {#if activeChunkIndex !== null}
                <button
                  type="button"
                  class="text-accent-stronger hover:bg-hover-default rounded px-2 py-1 text-xs font-medium"
                  onclick={resetChunkHighlight}
                >
                  {m.clear()}
                </button>
              {/if}
            </div>
            {#if chunkItems.length === 0}
              <p class="border-default bg-primary text-muted rounded-md border p-2 text-xs">
                {m.flow_run_knowledge_no_snippets()}
              </p>
            {:else}
              <div
                class="border-default divide-default flex max-h-[44vh] flex-col divide-y overflow-auto rounded-lg border"
              >
                {#each chunkItems as chunk, index (`${chunk.chunk_no ?? 0}-${index}`)}
                  <button
                    type="button"
                    class="hover:bg-hover-default w-full px-2.5 py-2 text-left text-xs transition-colors"
                    class:bg-accent-dimmer={activeChunkIndex === index}
                    onclick={() => activateChunk(index)}
                  >
                    <div class="flex items-center justify-between gap-2">
                      <span class="text-secondary font-semibold">
                        {m.flow_run_knowledge_chunk_label({ chunk: String(chunk.chunk_no ?? 0) })}
                      </span>
                      <Tooltip.Provider delayDuration={150}>
                        <Tooltip.Root>
                          <Tooltip.Trigger>
                            <span
                              class={[
                                "rounded-full px-1.5 py-0.5 text-xs font-medium",
                                getKnowledgeRelevanceBadgeClass(Number(chunk.score ?? 0))
                              ]}
                            >
                              {scoreLabel(Number(chunk.score ?? 0))}
                            </span>
                          </Tooltip.Trigger>
                          <Tooltip.Content>{Number(chunk.score ?? 0).toFixed(2)}</Tooltip.Content>
                        </Tooltip.Root>
                      </Tooltip.Provider>
                    </div>
                    <p class="text-muted mt-1 line-clamp-3 text-xs leading-relaxed">
                      {chunk.snippet}
                    </p>
                  </button>
                {/each}
              </div>
            {/if}
          </div>
        </aside>

        <section class="border-default bg-primary rounded-md border">
          {#if loadingDocument}
            <div class="text-secondary flex items-center gap-2 p-4 text-sm">
              <IconLoadingSpinner class="size-4 animate-spin" />
              {m.flow_run_knowledge_loading_document()}
            </div>
          {:else if loadError}
            <p class="text-negative-default p-4 text-sm">
              {m.flow_run_knowledge_document_load_failed()}
            </p>
          {:else if !documentText}
            <p class="text-muted p-4 text-sm">{m.empty()}</p>
          {:else}
            <div
              bind:this={textContainer}
              class="knowledge-document h-[52vh] overflow-auto px-4 py-3"
              style="content-visibility: auto;"
            >
              <pre
                class="font-sans text-[15px] leading-relaxed break-words whitespace-pre-wrap">{documentText}</pre>
            </div>
            <div
              class="border-default bg-hover-dimmer flex items-center justify-between border-t px-4 py-2.5"
            >
              <div class="text-muted inline-flex items-center gap-2 text-xs">
                <span class="legend-swatch"></span>
                <span>{m.flow_run_knowledge_highlight_legend()}</span>
              </div>
              <div class="inline-flex items-center gap-1">
                <Button variant="outline" class="text-xs" onclick={previousChunk}>
                  {m.flow_run_knowledge_prev_match()}
                </Button>
                <span class="text-muted px-2 text-xs tabular-nums">
                  {#if activeChunkIndex !== null}
                    {m.flow_run_knowledge_chunk_position({
                      current: String(activeChunkIndex + 1),
                      total: String(chunkItems.length)
                    })}
                  {:else if hasHiddenMatchedChunks}
                    {m.flow_run_knowledge_chunks_displayed_of_matched({
                      displayed: String(chunkItems.length),
                      matched: String(totalMatchedChunkCount)
                    })}
                  {:else}
                    {m.flow_run_knowledge_chunk_count({ count: String(chunkItems.length) })}
                  {/if}
                </span>
                <Button variant="outline" class="text-xs" onclick={nextChunk}>
                  {m.flow_run_knowledge_next_match()}
                </Button>
              </div>
            </div>
          {/if}
        </section>
      </div>
    </div>

    <Dialog.Footer>
      <Button variant="default" onclick={() => (isOpen = false)}>{m.done()}</Button>
    </Dialog.Footer>
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
