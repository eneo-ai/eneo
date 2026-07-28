<script lang="ts">
  import type { FlowRunDebugRag, Eneo } from "@eneo/eneo-js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import { IconChevronRight } from "@eneo/icons/chevron-right";
  import { m } from "$lib/paraglide/messages";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import FlowRunKnowledgeSourceRow from "./FlowRunKnowledgeSourceRow.svelte";
  import {
    flattenKnowledgeTraceSources,
    getKnowledgeReferencePreviewReferences,
    getKnowledgeTraceSourceTotal,
    isMappedFanOutIncomplete
  } from "./flowRunKnowledgeTrace";
  import { getKnowledgeSourceSearchText } from "./flowRunKnowledgePresentation";

  const INLINE_REFERENCE_LIMIT = 4;
  const MODAL_REFERENCE_LIMIT = 50;

  let {
    rag = null,
    eneo,
    stepOrder
  }: {
    rag?: FlowRunDebugRag | null | undefined;
    eneo: Eneo;
    stepOrder: number;
  } = $props();

  let expanded = $state(false);
  let didInit = $state(false);
  let showAllSources = $state(false);
  let sourceQuery = $state("");
  let normalizedSourceQuery = $derived(sourceQuery.trim().toLowerCase());

  // A mapped step records one payload per provider call, so sources are read
  // through the shared flattener rather than the top level alone.
  let traceSources = $derived(flattenKnowledgeTraceSources(rag));
  let sourceTotal = $derived(getKnowledgeTraceSourceTotal(rag, traceSources.length));
  // A fan-out that stopped early retrieved less than the step intended; saying
  // nothing would present a partial trace as a complete one.
  let mappedFanOutIncomplete = $derived(isMappedFanOutIncomplete(rag));
  // Every retrieved source is listed; only passage detail is bounded, so the
  // trace states the difference instead of claiming references were dropped.
  let passageDetailSummary = $derived.by(() => {
    const withheld = rag?.passages_withheld ?? 0;
    if (withheld > 0) {
      return m.flow_run_knowledge_passages_withheld({ count: String(withheld) });
    }
    const sourcesWithDetail = rag?.sources_with_recorded_passages;
    const totalSources = traceSources.length;
    if (
      typeof sourcesWithDetail === "number" &&
      totalSources > 0 &&
      sourcesWithDetail < totalSources
    ) {
      return m.flow_run_knowledge_passage_detail_partial({
        detailed: String(sourcesWithDetail),
        total: String(totalSources)
      });
    }
    return null;
  });

  let referencePreview = $derived(
    getKnowledgeReferencePreviewReferences(traceSources, INLINE_REFERENCE_LIMIT)
  );
  let searchableReferences = $derived(
    traceSources.map((source, index) => ({
      ...source,
      index,
      searchText: getKnowledgeSourceSearchText(source.reference)
    }))
  );
  let filteredReferenceMatches = $derived(
    normalizedSourceQuery.length === 0
      ? searchableReferences
      : searchableReferences.filter(({ searchText }) => searchText.includes(normalizedSourceQuery))
  );
  let visibleFilteredReferenceMatches = $derived(
    filteredReferenceMatches.slice(0, MODAL_REFERENCE_LIMIT)
  );

  $effect(() => {
    if (rag && traceSources && !didInit) {
      didInit = true;
      expanded = rag.status === "success" && traceSources.length > 0;
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
    <section class="bg-primary overflow-hidden">
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
          <div class="text-muted flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
            <span>{m.flow_run_knowledge_sources_label()}: {sourceTotal}</span>
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
          class="border-default flex flex-col gap-3 border-t px-4 py-3"
        >
          {#if rag.retrieval_error_type}
            <p class="text-muted text-xs">
              {m.flow_run_knowledge_error_type()}:
              <span class="font-mono">{rag.retrieval_error_type}</span>
            </p>
          {/if}

          {#if traceSources.length === 0}
            <p class="text-muted rounded-md px-3 py-6 text-center text-sm">
              {m.flow_run_knowledge_no_sources()}
            </p>
          {:else}
            <ol
              class="border-default bg-primary divide-default divide-y overflow-hidden rounded-lg border"
            >
              {#each referencePreview.references as source, index (source.key)}
                <FlowRunKnowledgeSourceRow
                  {eneo}
                  reference={source.reference}
                  callNumber={source.callNumber}
                  {index}
                />
              {/each}
            </ol>

            {#if referencePreview.hiddenCount > 0}
              <div
                class="border-default flex flex-col gap-3 border-t pt-3 sm:flex-row sm:items-center sm:justify-between"
              >
                <p class="text-muted text-xs">
                  {m.flow_run_knowledge_inline_sources_summary({
                    shown: String(referencePreview.references.length),
                    total: String(traceSources.length)
                  })}
                </p>
                <Button variant="outline" size="sm" onclick={() => (showAllSources = true)}>
                  {m.flow_run_knowledge_show_all_sources({
                    count: String(traceSources.length)
                  })}
                </Button>
              </div>
            {/if}
          {/if}

          {#if mappedFanOutIncomplete}
            <p class="text-warning-stronger text-xs" data-testid="mapped-fan-out-incomplete">
              {m.flow_run_knowledge_mapped_fan_out_incomplete()}
            </p>
          {/if}

          {#if passageDetailSummary}
            <p class="text-muted text-xs">{passageDetailSummary}</p>
          {/if}
        </div>
      </Collapsible.Content>
    </section>
  </Collapsible.Root>

  <Dialog.Root bind:open={showAllSources}>
    <Dialog.Content class="!flex max-h-[86vh] !max-w-4xl flex-col !gap-0 overflow-hidden !p-0">
      <Dialog.Header class="px-5 pt-5 pb-3">
        <Dialog.Title>{m.flow_run_knowledge_all_sources_title()}</Dialog.Title>
        <Dialog.Description>
          {m.flow_run_knowledge_all_sources_description({
            count: String(traceSources.length)
          })}
        </Dialog.Description>
      </Dialog.Header>

      <div class="border-default bg-primary flex flex-col gap-2 border-b px-5 pb-3">
        <Input
          bind:value={sourceQuery}
          placeholder={m.flow_run_knowledge_filter_sources_placeholder()}
          aria-label={m.flow_run_knowledge_filter_sources_placeholder()}
        />
        <p class="text-muted text-xs">
          {m.flow_run_knowledge_filter_sources_summary({
            shown: String(visibleFilteredReferenceMatches.length),
            total: String(filteredReferenceMatches.length)
          })}
        </p>
      </div>

      <div class="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {#if filteredReferenceMatches.length === 0}
          <p class="text-muted rounded-md px-3 py-6 text-center text-sm">
            {m.flow_run_knowledge_no_matching_sources()}
          </p>
        {:else}
          <ol
            class="border-default bg-primary divide-default divide-y overflow-hidden rounded-lg border"
          >
            {#each visibleFilteredReferenceMatches as { reference, callNumber, index, key } (key)}
              <FlowRunKnowledgeSourceRow {eneo} {reference} {callNumber} {index} />
            {/each}
          </ol>
          {#if visibleFilteredReferenceMatches.length < filteredReferenceMatches.length}
            <p class="text-muted rounded-md px-3 py-6 text-center text-sm">
              {m.flow_run_knowledge_filter_sources_limit_hint({
                shown: String(visibleFilteredReferenceMatches.length),
                total: String(filteredReferenceMatches.length)
              })}
            </p>
          {/if}
        {/if}
      </div>
    </Dialog.Content>
  </Dialog.Root>
{/if}
