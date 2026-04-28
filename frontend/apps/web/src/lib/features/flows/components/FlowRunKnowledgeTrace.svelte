<script lang="ts">
  import type { FlowRunDebugRag, FlowRunDebugRagReference, Intric } from "@intric/intric-js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import { IconChevronRight } from "@intric/icons/chevron-right";
  import { m } from "$lib/paraglide/messages";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import FlowRunKnowledgeSourceCard from "./FlowRunKnowledgeSourceCard.svelte";
  import { getKnowledgeReferencePreviewReferences } from "./flowRunKnowledgeTrace";

  const INLINE_REFERENCE_LIMIT = 4;

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
  let showAllSources = $state(false);
  let sourceQuery = $state("");

  let references = $derived(
    ((rag?.references ?? []) as FlowRunDebugRagReference[]).filter(
      (reference) => typeof reference?.id === "string" && reference.id.length > 0
    )
  );
  let referencePreview = $derived(
    getKnowledgeReferencePreviewReferences(references, INLINE_REFERENCE_LIMIT)
  );
  let filteredReferences = $derived(
    sourceQuery.trim().length === 0
      ? references
      : references.filter((reference) => {
          const query = sourceQuery.trim().toLowerCase();
          return [reference.title, reference.id_short, reference.id]
            .filter((value): value is string => typeof value === "string")
            .some((value) => value.toLowerCase().includes(query));
        })
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
</script>

{#if rag}
  <Collapsible.Root bind:open={expanded}>
    <Card.Root class="bg-primary overflow-hidden">
      <Collapsible.Trigger
        class="hover:bg-hover-dimmer focus-visible:ring-accent-default/30 flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset"
        aria-controls={`flow-knowledge-trace-${stepOrder}`}
      >
        <div class="flex min-w-0 flex-col gap-1">
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-muted text-xs font-semibold">{m.flow_run_knowledge_trace()}</span>
            <span
              class={[
                "inline-flex items-center gap-1.5 text-xs font-medium",
                statusClass(rag.status)
              ]}
            >
              <span class="size-1.5 rounded-full bg-current opacity-80"></span>
              {statusLabel(rag.status)}
            </span>
          </div>
          <div class="text-muted flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px]">
            <span
              >{m.flow_run_knowledge_sources_label()}: {rag.unique_sources ??
                references.length}</span
            >
            <span aria-hidden="true">&middot;</span>
            <span>{m.flow_run_knowledge_chunks_label()}: {rag.chunks_retrieved ?? 0}</span>
            <span aria-hidden="true">&middot;</span>
            <span
              >{m.flow_run_knowledge_latency_label()}: {formatLatency(
                rag.retrieval_duration_ms
              )}</span
            >
          </div>
        </div>
        <IconChevronRight
          class={expanded
            ? "text-muted size-4 shrink-0 rotate-90 transition-transform duration-200"
            : "text-muted size-4 shrink-0 transition-transform duration-200"}
        />
      </Collapsible.Trigger>

      <Collapsible.Content>
        <div
          id={`flow-knowledge-trace-${stepOrder}`}
          class="border-default flex flex-col gap-3 border-t px-4 py-4"
        >
          <div
            class="border-default bg-hover-dimmer text-muted flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border px-3 py-2 text-xs"
          >
            <span class={["inline-flex items-center gap-1.5 font-medium", statusClass(rag.status)]}>
              <span class="size-1.5 rounded-full bg-current opacity-80"></span>
              {m.flow_run_knowledge_status_label()}: {statusLabel(rag.status)}
            </span>
            <span
              >{m.flow_run_knowledge_sources_label()}: {rag.unique_sources ??
                references.length}</span
            >
            <span>{m.flow_run_knowledge_chunks_label()}: {rag.chunks_retrieved ?? 0}</span>
            <span
              >{m.flow_run_knowledge_latency_label()}: {formatLatency(
                rag.retrieval_duration_ms
              )}</span
            >
            <span>{m.flow_run_knowledge_version_label()}: v{rag.version ?? 1}</span>
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
            <div class="flex flex-col gap-2">
              {#each referencePreview.references as reference, index (reference.id)}
                <FlowRunKnowledgeSourceCard {intric} {reference} {index} />
              {/each}
            </div>

            {#if referencePreview.hiddenCount > 0}
              <div
                class="border-default bg-hover-dimmer flex flex-col gap-3 rounded-lg border px-3 py-3 sm:flex-row sm:items-center sm:justify-between"
              >
                <p class="text-muted text-xs">
                  {m.flow_run_knowledge_inline_sources_summary({
                    shown: String(referencePreview.references.length),
                    total: String(references.length)
                  })}
                </p>
                <Button variant="outline" size="sm" onclick={() => (showAllSources = true)}>
                  {m.flow_run_knowledge_show_all_sources({
                    count: String(references.length)
                  })}
                </Button>
              </div>
            {/if}
          {/if}

          {#if rag.references_truncated}
            <p class="text-muted text-xs">{m.flow_run_knowledge_references_truncated()}</p>
          {/if}
        </div>
      </Collapsible.Content>
    </Card.Root>
  </Collapsible.Root>

  <Dialog.Root bind:open={showAllSources}>
    <Dialog.Content class="!max-w-5xl">
      <Dialog.Header>
        <Dialog.Title>{m.flow_run_knowledge_all_sources_title()}</Dialog.Title>
        <Dialog.Description>
          {m.flow_run_knowledge_all_sources_description({
            count: String(references.length)
          })}
        </Dialog.Description>
      </Dialog.Header>

      <div class="border-default bg-primary sticky top-0 z-10 flex flex-col gap-2 border-b pb-3">
        <Input
          bind:value={sourceQuery}
          placeholder={m.flow_run_knowledge_filter_sources_placeholder()}
          aria-label={m.flow_run_knowledge_filter_sources_placeholder()}
        />
        <p class="text-muted text-xs">
          {m.flow_run_knowledge_filter_sources_summary({
            shown: String(filteredReferences.length),
            total: String(references.length)
          })}
        </p>
      </div>

      <div class="max-h-[62vh] overflow-y-auto pr-1">
        <div class="flex flex-col gap-1.5 py-3">
          {#if filteredReferences.length === 0}
            <p class="text-muted rounded-md px-3 py-6 text-center text-sm">
              {m.flow_run_knowledge_no_matching_sources()}
            </p>
          {:else}
            {#each filteredReferences as reference, index (reference.id)}
              <FlowRunKnowledgeSourceCard {intric} {reference} {index} />
            {/each}
          {/if}
        </div>
      </div>
    </Dialog.Content>
  </Dialog.Root>
{/if}
