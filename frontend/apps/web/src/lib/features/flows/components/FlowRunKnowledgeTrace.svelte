<script lang="ts">
  import type { FlowRunDebugRag, FlowRunDebugRagReference, Intric } from "@intric/intric-js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import { IconChevronRight } from "@intric/icons/chevron-right";
  import { m } from "$lib/paraglide/messages";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import FlowChunkViewer from "./FlowChunkViewer.svelte";

  let {
    rag = null,
    intric,
    stepOrder
  }: {
    rag?: FlowRunDebugRag | null | undefined;
    intric: Intric;
    stepOrder: number;
  } = $props();

  let expanded = $state(false);
  let didInit = $state(false);

  let references = $derived(
    ((rag?.references ?? []) as FlowRunDebugRagReference[]).filter(
      (reference) => typeof reference?.id === "string" && reference.id.length > 0
    )
  );

  $effect(() => {
    if (rag && references && !didInit) {
      didInit = true;
      expanded = rag.status === "success" && references.length > 0;
    }
  });

  function statusClass(status: string | null | undefined): string {
    switch (status) {
      case "success":
        return "text-positive-stronger";
      case "timeout":
      case "error":
        return "text-negative-stronger";
      default:
        return "text-secondary";
    }
  }

  function statusLabel(status: string | null | undefined): string {
    switch (status) {
      case "success":
        return m.flow_run_knowledge_status_success();
      case "timeout":
        return m.flow_run_knowledge_status_timeout();
      case "error":
        return m.flow_run_knowledge_status_error();
      case "skipped_no_knowledge":
        return m.flow_run_knowledge_status_skipped_no_knowledge();
      case "skipped_no_input":
        return m.flow_run_knowledge_status_skipped_no_input();
      case "skipped_no_service":
        return m.flow_run_knowledge_status_skipped_no_service();
      default:
        return status ?? m.unknown();
    }
  }

  function formatLatency(value: number | null | undefined): string {
    if (value === null || value === undefined) {
      return "\u2014";
    }
    return `${value}ms`;
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

{#if rag}
  <Collapsible.Root bind:open={expanded}>
    <Card.Root>
      <Collapsible.Trigger
        class="hover:bg-hover-dimmer flex w-full items-center justify-between px-3 py-2 text-left"
        aria-controls={`flow-knowledge-trace-${stepOrder}`}
      >
        <div class="flex items-center gap-2">
          <span class="text-muted text-xs font-semibold">{m.flow_run_knowledge_trace()}</span>
          <span class={["text-xs font-medium", statusClass(rag.status)]}
            >{statusLabel(rag.status)}</span
          >
        </div>
        <IconChevronRight
          class={expanded ? "size-4 rotate-90 transition-transform" : "size-4 transition-transform"}
        />
      </Collapsible.Trigger>

      <Collapsible.Content>
        <div
          id={`flow-knowledge-trace-${stepOrder}`}
          class="border-default space-y-3 border-t px-3 py-3"
        >
          <div class="flex flex-wrap gap-2">
            <Badge variant="outline" class={statusClass(rag.status)}>
              <span class="mr-1 inline-block size-1.5 rounded-full bg-current opacity-80"></span>
              {m.flow_run_knowledge_status_label()}: {statusLabel(rag.status)}
            </Badge>
            <Badge variant="outline">
              {m.flow_run_knowledge_sources_label()}: {rag.unique_sources ?? references.length}
            </Badge>
            <Badge variant="outline">
              {m.flow_run_knowledge_chunks_label()}: {rag.chunks_retrieved ?? 0}
            </Badge>
            <Badge variant="outline">
              {m.flow_run_knowledge_latency_label()}: {formatLatency(rag.retrieval_duration_ms)}
            </Badge>
            <Badge variant="outline">
              {m.flow_run_knowledge_version_label()}: v{rag.version ?? 1}
            </Badge>
          </div>

          {#if rag.retrieval_error_type}
            <p class="text-muted text-xs">
              {m.flow_run_knowledge_error_type()}:
              <span class="font-mono">{rag.retrieval_error_type}</span>
            </p>
          {/if}

          {#if references.length === 0}
            <Card.Root size="sm" class="bg-hover-dimmer">
              <Card.Content class="p-3">
                <p class="text-muted text-sm">
                  {m.flow_run_knowledge_no_sources()}
                </p>
              </Card.Content>
            </Card.Root>
          {:else}
            <div class="space-y-2">
              {#each references as reference, index (reference.id)}
                <FlowChunkViewer
                  {intric}
                  infoBlobId={reference.id}
                  title={reference.title ?? null}
                  sourceIdShort={reference.id_short ?? reference.id.slice(0, 8)}
                  chunks={reference.chunks ?? []}
                >
                  {#snippet children({ showViewer })}
                    <Card.Root
                      class="group hover:border-accent-default transition-all hover:shadow-sm"
                    >
                      <button
                        class="focus-visible:ring-accent-default w-full p-3 text-left focus-visible:ring-2 focus-visible:outline-none"
                        onclick={showViewer}
                      >
                        <div class="flex items-start justify-between gap-4">
                          <div class="min-w-0">
                            <div class="flex items-center gap-2">
                              <Badge
                                variant="outline"
                                class="size-6 shrink-0 justify-center rounded-full p-0 text-[11px] font-semibold"
                              >
                                {index + 1}
                              </Badge>
                              <p
                                class="group-hover:text-accent-stronger truncate text-sm font-medium"
                              >
                                {getDisplayTitle(reference) ||
                                  m.flow_run_knowledge_untitled_source()}
                              </p>
                            </div>
                            <div class="mt-1">
                              <Tooltip.Provider delayDuration={150}>
                                <Tooltip.Root>
                                  <Tooltip.Trigger>
                                    <span class="text-muted font-mono text-[10px]"
                                      >{reference.id_short ?? reference.id.slice(0, 8)}</span
                                    >
                                  </Tooltip.Trigger>
                                  <Tooltip.Content>{reference.id}</Tooltip.Content>
                                </Tooltip.Root>
                              </Tooltip.Provider>
                            </div>
                          </div>

                          <div class="shrink-0 text-right text-xs">
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
                                <Tooltip.Content
                                  >{Number(reference.best_score ?? 0).toFixed(2)}</Tooltip.Content
                                >
                              </Tooltip.Root>
                            </Tooltip.Provider>
                            <p class="text-muted mt-0.5">
                              {m.flow_run_knowledge_chunks_matched({
                                count: String(reference.hit_count ?? reference.chunks?.length ?? 0)
                              })}
                            </p>
                          </div>
                        </div>

                        {#if reference.chunks && reference.chunks.length > 0}
                          {@const sortedChunks = [...reference.chunks].sort(
                            (a, b) => (a.chunk_no ?? 0) - (b.chunk_no ?? 0)
                          )}
                          {@const displayChunks = sortedChunks.slice(0, 4)}
                          {@const remainingCount = sortedChunks.length - displayChunks.length}
                          <div class="mt-2 grid gap-2 md:grid-cols-2">
                            {#each displayChunks as chunk (chunk.chunk_no)}
                              <Card.Root size="sm" class="bg-hover-dimmer">
                                <Card.Content class="px-2.5 py-2 text-xs">
                                  <div class="text-muted flex items-center justify-between">
                                    <span
                                      >{m.flow_run_knowledge_chunk_label({
                                        chunk: String(chunk.chunk_no)
                                      })}</span
                                    >
                                    <Tooltip.Provider delayDuration={150}>
                                      <Tooltip.Root>
                                        <Tooltip.Trigger>
                                          <Badge
                                            class={[
                                              "rounded-full text-[10px]",
                                              scoreBadgeClass(Number(chunk.score ?? 0))
                                            ]}
                                          >
                                            {scoreLabel(Number(chunk.score ?? 0))}
                                          </Badge>
                                        </Tooltip.Trigger>
                                        <Tooltip.Content
                                          >{Number(chunk.score ?? 0).toFixed(2)}</Tooltip.Content
                                        >
                                      </Tooltip.Root>
                                    </Tooltip.Provider>
                                  </div>
                                  <p class="text-secondary mt-1 line-clamp-2">{chunk.snippet}</p>
                                </Card.Content>
                              </Card.Root>
                            {/each}
                          </div>
                          {#if remainingCount > 0}
                            <p class="text-muted mt-1.5 text-center text-[11px]">
                              {m.flow_run_knowledge_more_segments({
                                count: String(remainingCount)
                              })}
                            </p>
                          {/if}
                        {/if}

                        <div
                          class="text-muted mt-2 flex items-center justify-end gap-1 text-xs
                                    opacity-40 transition-opacity group-hover:opacity-100"
                        >
                          <span>{m.flow_run_knowledge_open_viewer()}</span>
                          <IconChevronRight class="size-3" />
                        </div>
                      </button>
                    </Card.Root>
                  {/snippet}
                </FlowChunkViewer>
              {/each}
            </div>
          {/if}

          {#if rag.references_truncated}
            <p class="text-muted text-xs">{m.flow_run_knowledge_references_truncated()}</p>
          {/if}
        </div>
      </Collapsible.Content>
    </Card.Root>
  </Collapsible.Root>
{/if}
