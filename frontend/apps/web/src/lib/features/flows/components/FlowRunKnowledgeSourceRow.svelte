<script lang="ts">
  import type { FlowRunDebugRagReference, Eneo } from "@eneo/eneo-js";
  import { IconChevronRight } from "@eneo/icons/chevron-right";
  import { m } from "$lib/paraglide/messages";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import FlowChunkViewer from "./FlowChunkViewer.svelte";
  import { getKnowledgeReferenceCounts } from "./flowRunKnowledgeTrace";
  import {
    formatKnowledgeSourceLabel,
    getKnowledgeRelevanceBadgeClass,
    getKnowledgeRelevanceLevel
  } from "./flowRunKnowledgePresentation";

  let {
    reference,
    index,
    eneo
  }: {
    reference: FlowRunDebugRagReference;
    index: number;
    eneo: Eneo;
  } = $props();

  let counts = $derived(getKnowledgeReferenceCounts(reference));
  let displayTitle = $derived(
    formatKnowledgeSourceLabel(
      reference.display_title ?? reference.source_display_name ?? reference.title,
      reference.source_url
    ) || m.flow_run_knowledge_untitled_source()
  );

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
</script>

<FlowChunkViewer
  {eneo}
  infoBlobId={reference.id}
  title={reference.title ?? null}
  sourceIdShort={reference.id_short ?? reference.id.slice(0, 8)}
  chunks={reference.chunks ?? []}
  matchedChunkCount={counts.matchedCount}
>
  {#snippet children({ showViewer })}
    <li>
      <button
        type="button"
        class="group hover:bg-hover-dimmer focus-visible:ring-accent-default/30 flex min-h-16 w-full items-center justify-between gap-3 px-3 py-3 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset sm:px-4"
        aria-label={`${m.flow_run_knowledge_open_viewer()}: ${displayTitle}`}
        onclick={showViewer}
      >
        <div class="flex min-w-0 items-center gap-3">
          <Badge
            variant="outline"
            class="size-6 shrink-0 justify-center rounded-full p-0 text-xs font-semibold"
          >
            {index + 1}
          </Badge>
          <div class="min-w-0">
            <p class="group-hover:text-accent-stronger truncate text-sm font-semibold">
              {displayTitle}
            </p>
            <div class="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
              <Tooltip.Provider delayDuration={150}>
                <Tooltip.Root>
                  <Tooltip.Trigger>
                    <span class="text-muted font-mono text-xs">
                      {reference.id_short ?? reference.id.slice(0, 8)}
                    </span>
                  </Tooltip.Trigger>
                  <Tooltip.Content>{reference.id}</Tooltip.Content>
                </Tooltip.Root>
              </Tooltip.Provider>
              <span class="text-muted text-xs">
                {#if counts.truncated}
                  {m.flow_run_knowledge_chunks_displayed_of_matched({
                    displayed: String(counts.displayedCount),
                    matched: String(counts.matchedCount)
                  })}
                {:else}
                  {m.flow_run_knowledge_chunks_matched({
                    count: String(counts.matchedCount)
                  })}
                {/if}
              </span>
            </div>
          </div>
        </div>

        <div class="flex shrink-0 items-center gap-2">
          <Tooltip.Provider delayDuration={150}>
            <Tooltip.Root>
              <Tooltip.Trigger>
                <Badge
                  class={[
                    "rounded-full text-xs",
                    getKnowledgeRelevanceBadgeClass(Number(reference.best_score ?? 0))
                  ]}
                >
                  {scoreLabel(Number(reference.best_score ?? 0))}
                </Badge>
              </Tooltip.Trigger>
              <Tooltip.Content class="max-w-72">
                {m.flow_run_knowledge_relevance_tooltip({
                  score: Number(reference.best_score ?? 0).toFixed(2)
                })}
              </Tooltip.Content>
            </Tooltip.Root>
          </Tooltip.Provider>
          <span
            class="text-muted hidden text-xs opacity-60 transition-opacity group-hover:opacity-100 sm:inline"
          >
            {m.flow_run_knowledge_open_viewer()}
          </span>
          <IconChevronRight
            class="text-muted size-4 opacity-60 transition-opacity group-hover:opacity-100"
          />
        </div>
      </button>
    </li>
  {/snippet}
</FlowChunkViewer>
