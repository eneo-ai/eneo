<script lang="ts">
  import type {
    FlowRunDebugRag,
    FlowRunDebugRagReference,
    Intric,
  } from "@intric/intric-js";
  import { Tooltip } from "@intric/ui";
  import { IconChevronRight } from "@intric/icons/chevron-right";
  import { m } from "$lib/paraglide/messages";
  import FlowChunkViewer from "./FlowChunkViewer.svelte";

  export let rag: FlowRunDebugRag | null | undefined = null;
  export let intric: Intric;
  export let stepOrder: number;

  let expanded = false;
  let didInit = false;

  $: references = ((rag?.references ?? []) as FlowRunDebugRagReference[]).filter(
    (reference) => typeof reference?.id === "string" && reference.id.length > 0,
  );

  $: if (rag && references && !didInit) {
    didInit = true;
    expanded = rag.status === "success" && references.length > 0;
  }

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
      return "—";
    }
    return `${value}ms`;
  }

  function scoreColorClass(score: number): string {
    if (score >= 0.5) return "text-positive-stronger";
    if (score >= 0.3) return "text-warning-stronger";
    return "text-negative-stronger";
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
</script>

<svelte:options runes={false} />

{#if rag}
  <div
    class="rounded-lg border border-default bg-primary"
    style:border-left={expanded ? "2px solid var(--accent-default)" : undefined}
  >
    <button
      class="flex w-full items-center justify-between px-3 py-2 text-left hover:bg-hover-dimmer"
      aria-expanded={expanded}
      aria-controls={`flow-knowledge-trace-${stepOrder}`}
      on:click={() => (expanded = !expanded)}
    >
      <div class="flex items-center gap-2">
        <span class="text-xs font-semibold text-muted">{m.flow_run_knowledge_trace()}</span>
        <span class={["text-xs font-medium", statusClass(rag.status)]}>{statusLabel(rag.status)}</span>
      </div>
      <IconChevronRight class={expanded ? "size-4 rotate-90 transition-transform" : "size-4 transition-transform"} />
    </button>

    {#if expanded}
      <div id={`flow-knowledge-trace-${stepOrder}`} class="space-y-3 border-t border-default px-3 py-3">
        <div class="flex flex-wrap gap-2">
          <span class={["rounded-md border px-2 py-1 text-[11px]", statusClass(rag.status)]}>
            <span class="mr-1 inline-block size-1.5 rounded-full bg-current opacity-80"></span>
            {m.flow_run_knowledge_status_label()}: {statusLabel(rag.status)}
          </span>
          <span class="rounded-md border border-default bg-hover-dimmer px-2 py-1 text-[11px] text-muted">
            {m.flow_run_knowledge_sources_label()}: {rag.unique_sources ?? references.length}
          </span>
          <span class="rounded-md border border-default bg-hover-dimmer px-2 py-1 text-[11px] text-muted">
            {m.flow_run_knowledge_chunks_label()}: {rag.chunks_retrieved ?? 0}
          </span>
          <span class="rounded-md border border-default bg-hover-dimmer px-2 py-1 text-[11px] text-muted">
            {m.flow_run_knowledge_latency_label()}: {formatLatency(rag.retrieval_duration_ms)}
          </span>
          <span class="rounded-md border border-default bg-hover-dimmer px-2 py-1 text-[11px] text-muted">
            {m.flow_run_knowledge_version_label()}: v{rag.version ?? 1}
          </span>
        </div>

        {#if rag.retrieval_error_type}
          <p class="text-xs text-muted">
            {m.flow_run_knowledge_error_type()}: <span class="font-mono">{rag.retrieval_error_type}</span>
          </p>
        {/if}

        {#if references.length === 0}
          <p class="rounded-md border border-default bg-hover-dimmer p-3 text-sm text-muted">
            {m.flow_run_knowledge_no_sources()}
          </p>
        {:else}
          <div class="space-y-2">
            {#each references as reference, index (reference.id)}
              <FlowChunkViewer
                {intric}
                infoBlobId={reference.id}
                title={reference.title ?? null}
                sourceIdShort={reference.id_short ?? reference.id.slice(0, 8)}
                chunks={reference.chunks ?? []}
                let:showViewer
              >
                <button
                  class="group w-full rounded-md border border-default bg-primary p-3 text-left
                         transition-all hover:border-accent-default hover:shadow-sm
                         focus-visible:ring-2 focus-visible:ring-accent-default focus-visible:outline-none"
                  on:click={showViewer}
                >
                  <div class="flex items-start justify-between gap-4">
                    <div class="min-w-0">
                      <div class="flex items-center gap-2">
                        <span class="inline-flex size-6 items-center justify-center rounded-full border border-default bg-hover-dimmer text-[11px] font-semibold">
                          {index + 1}
                        </span>
                        <p class="truncate text-sm font-medium group-hover:text-accent-stronger">
                          {cleanTitle(reference.title) || m.flow_run_knowledge_untitled_source()}
                        </p>
                      </div>
                      <div class="mt-1">
                        <Tooltip text={reference.id}>
                          <span class="font-mono text-[10px] text-muted opacity-60">{reference.id_short ?? reference.id.slice(0, 8)}</span>
                        </Tooltip>
                      </div>
                    </div>

                    <div class="shrink-0 text-right text-xs text-muted">
                      <p class={["font-medium", scoreColorClass(Number(reference.best_score ?? 0))]}>
                        {m.flow_run_knowledge_best_score_label({
                          score: String(Number(reference.best_score ?? 0).toFixed(3)),
                        })}
                      </p>
                      <p>
                        {m.flow_run_knowledge_chunks_matched({
                          count: String(reference.hit_count ?? reference.chunks?.length ?? 0),
                        })}
                      </p>
                    </div>
                  </div>

                  {#if reference.chunks && reference.chunks.length > 0}
                    {@const sortedChunks = [...reference.chunks].sort((a, b) => (a.chunk_no ?? 0) - (b.chunk_no ?? 0))}
                    {@const displayChunks = sortedChunks.slice(0, 4)}
                    {@const remainingCount = sortedChunks.length - displayChunks.length}
                    <div class="mt-2 grid gap-2 md:grid-cols-2">
                      {#each displayChunks as chunk (chunk.chunk_no)}
                        <div class="rounded-md border border-default bg-hover-dimmer px-2.5 py-2 text-xs">
                          <div class="flex items-center justify-between text-muted">
                            <span>{m.flow_run_knowledge_chunk_label({ chunk: String(chunk.chunk_no) })}</span>
                            <span class={scoreColorClass(Number(chunk.score ?? 0))}>{m.flow_run_knowledge_score_label({ score: String(Number(chunk.score).toFixed(3)) })}</span>
                          </div>
                          <p class="mt-1 line-clamp-2 text-secondary">{chunk.snippet}</p>
                        </div>
                      {/each}
                    </div>
                    {#if remainingCount > 0}
                      <p class="mt-1.5 text-center text-[11px] text-muted">
                        {m.flow_run_knowledge_more_segments({ count: String(remainingCount) })}
                      </p>
                    {/if}
                  {/if}

                  <div class="mt-2 flex items-center justify-end gap-1 text-xs text-muted
                              opacity-0 transition-opacity group-hover:opacity-100">
                    <span>{m.flow_run_knowledge_open_viewer()}</span>
                    <IconChevronRight class="size-3" />
                  </div>
                </button>
              </FlowChunkViewer>
            {/each}
          </div>
        {/if}

        {#if rag.references_truncated}
          <p class="text-xs text-muted">{m.flow_run_knowledge_references_truncated()}</p>
        {/if}
      </div>
    {/if}
  </div>
{/if}
