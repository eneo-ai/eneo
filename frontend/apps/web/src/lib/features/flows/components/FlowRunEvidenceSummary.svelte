<script lang="ts">
  import { toast } from "svelte-sonner";
  import type { FlowRunSummary, FlowRunTokenUsage, FlowRunTranscriptionUsage } from "@eneo/eneo-js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { m } from "$lib/paraglide/messages";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import FlowRunStatusBadge from "./FlowRunStatusBadge.svelte";
  import FlowRunTokenUsageBadge from "./FlowRunTokenUsageBadge.svelte";
  import FlowRunTranscriptionUsageBadge from "./FlowRunTranscriptionUsageBadge.svelte";

  let {
    runStatus,
    traceId = null,
    redactionApplied = false,
    tokenUsage = null,
    transcriptionUsage = null
  }: {
    runStatus: FlowRunSummary["status"];
    traceId?: string | null;
    redactionApplied?: boolean;
    tokenUsage?: FlowRunTokenUsage | null;
    transcriptionUsage?: FlowRunTranscriptionUsage | null;
  } = $props();

  // The row that was expanded already states the run's status, so a card
  // carrying nothing else would only repeat it.
  const hasRunDetail = $derived(
    Boolean(tokenUsage || transcriptionUsage || traceId || redactionApplied)
  );
  let traceCopied = $state(false);
  let traceCopiedTimer: ReturnType<typeof setTimeout> | null = null;

  async function copyTraceId() {
    if (!traceId) return;
    try {
      await navigator.clipboard.writeText(traceId);
      traceCopied = true;
      if (traceCopiedTimer) clearTimeout(traceCopiedTimer);
      traceCopiedTimer = setTimeout(() => (traceCopied = false), 1600);
    } catch (error) {
      console.error("Could not copy the trace id", error);
      toast.error(m.flow_run_copy_failed());
    }
  }
</script>

{#if hasRunDetail}
  <Card.Root>
    <Card.Content class="flex flex-wrap items-center gap-2 px-4 py-3">
      <FlowRunStatusBadge status={runStatus} size="md" showDot={false} />
      {#if tokenUsage}
        <FlowRunTokenUsageBadge {tokenUsage} />
      {/if}
      {#if transcriptionUsage}
        <FlowRunTranscriptionUsageBadge {transcriptionUsage} />
      {/if}
      {#if traceId}
        <!-- The badge's own text changing is invisible to a screen reader: the live
           region announces the same confirmation. -->
        <span class="sr-only" role="status" aria-live="polite">
          {traceCopied ? m.flow_run_evidence_trace_id_copied() : ""}
        </span>
        <Tooltip.Provider delayDuration={150}>
          <Tooltip.Root>
            <!-- The full identifier is support material, not something a municipal
               user reads: a 36-character UUID dominated a row of human facts. The
               badge shows the short form and copies the whole value, so a touch
               user who never sees a tooltip can still hand it to support. -->
            <Tooltip.Trigger
              onclick={copyTraceId}
              aria-label={m.flow_run_evidence_trace_id_copy()}
              class="focus-visible:ring-ring/40 rounded-full focus-visible:ring-2 focus-visible:outline-none"
            >
              <Badge variant="outline" class="font-mono text-xs">
                {traceCopied
                  ? m.flow_run_evidence_trace_id_copied()
                  : `${m.flow_run_evidence_trace_id()}: ${traceId.slice(0, 8)}…`}
              </Badge>
            </Tooltip.Trigger>
            <Tooltip.Content class="max-w-xs">
              <span class="block">{m.flow_run_evidence_trace_id_tooltip()}</span>
              <span class="mt-1 block font-mono break-all">{traceId}</span>
              <span class="text-muted mt-1 block">{m.flow_run_evidence_trace_id_copy()}</span>
            </Tooltip.Content>
          </Tooltip.Root>
        </Tooltip.Provider>
      {/if}
      {#if redactionApplied}
        <Tooltip.Provider delayDuration={150}>
          <Tooltip.Root>
            <Tooltip.Trigger>
              <Badge variant="outline" class="text-xs">
                {m.flow_run_evidence_redacted()}
              </Badge>
            </Tooltip.Trigger>
            <Tooltip.Content>{m.flow_run_evidence_redacted_tooltip()}</Tooltip.Content>
          </Tooltip.Root>
        </Tooltip.Provider>
      {/if}
    </Card.Content>
  </Card.Root>
{/if}
