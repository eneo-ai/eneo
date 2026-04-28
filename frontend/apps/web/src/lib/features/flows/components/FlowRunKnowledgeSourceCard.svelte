<script lang="ts">
  import type { FlowRunDebugRagReference, Intric } from "@intric/intric-js";
  import { IconChevronRight } from "@intric/icons/chevron-right";
  import { m } from "$lib/paraglide/messages";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import FlowChunkViewer from "./FlowChunkViewer.svelte";
  import { getKnowledgeReferenceMatchCount } from "./flowRunKnowledgeTrace";

  let {
    reference,
    index,
    intric
  }: {
    reference: FlowRunDebugRagReference;
    index: number;
    intric: Intric;
  } = $props();

  let matchCount = $derived(getKnowledgeReferenceMatchCount(reference));

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

  function cleanTitle(title: string | null | undefined): string {
    if (!title) return "";
    if (!title.startsWith("http")) return title;
    try {
      const u = new URL(title);
      const path = u.pathname.length > 40 ? u.pathname.slice(0, 37) + "..." : u.pathname;
      return u.hostname + (path === "/" ? "" : path);
    } catch {
      return title.slice(0, 60);
    }
  }

  function getDisplayTitle(reference: FlowRunDebugRagReference): string {
    const rawDisplayTitle = (
      reference as FlowRunDebugRagReference & { display_title?: string | null }
    ).display_title;
    if (rawDisplayTitle && rawDisplayTitle.trim().length > 0) {
      return rawDisplayTitle;
    }
    return cleanTitle(reference.title);
  }
</script>

<FlowChunkViewer
  {intric}
  infoBlobId={reference.id}
  title={reference.title ?? null}
  sourceIdShort={reference.id_short ?? reference.id.slice(0, 8)}
  chunks={reference.chunks ?? []}
>
  {#snippet children({ showViewer })}
    <Card.Root
      class="group hover:border-accent-default/50 overflow-hidden transition-[border-color,box-shadow] duration-200 hover:shadow-sm"
    >
      <button
        class="focus-visible:ring-accent-default/30 flex min-h-14 w-full items-center justify-between gap-4 p-3 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset"
        onclick={showViewer}
      >
        <div class="flex min-w-0 items-center gap-3">
          <Badge
            variant="outline"
            class="size-6 shrink-0 justify-center rounded-full p-0 text-[11px] font-semibold"
          >
            {index + 1}
          </Badge>
          <div class="min-w-0">
            <p class="group-hover:text-accent-stronger truncate text-sm font-semibold">
              {getDisplayTitle(reference) || m.flow_run_knowledge_untitled_source()}
            </p>
            <div class="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
              <Tooltip.Provider delayDuration={150}>
                <Tooltip.Root>
                  <Tooltip.Trigger>
                    <span class="text-muted font-mono text-[10px]">
                      {reference.id_short ?? reference.id.slice(0, 8)}
                    </span>
                  </Tooltip.Trigger>
                  <Tooltip.Content>{reference.id}</Tooltip.Content>
                </Tooltip.Root>
              </Tooltip.Provider>
              <span class="text-muted text-xs">
                {m.flow_run_knowledge_chunks_matched({
                  count: String(matchCount)
                })}
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
                    "rounded-full text-[11px]",
                    scoreBadgeClass(Number(reference.best_score ?? 0))
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
    </Card.Root>
  {/snippet}
</FlowChunkViewer>
