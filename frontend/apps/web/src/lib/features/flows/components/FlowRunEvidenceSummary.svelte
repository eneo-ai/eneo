<script lang="ts">
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { m } from "$lib/paraglide/messages";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import FlowRunStatusBadge from "./FlowRunStatusBadge.svelte";

  let {
    runStatus,
    traceId = null,
    redactionApplied = false
  }: {
    runStatus: string;
    traceId?: string | null;
    redactionApplied?: boolean;
  } = $props();
</script>

<Card.Root>
  <Card.Content class="flex flex-wrap items-center gap-2 px-4 py-3">
    <FlowRunStatusBadge status={runStatus} size="md" showDot={false} />
    {#if traceId}
      <Tooltip.Provider delayDuration={150}>
        <Tooltip.Root>
          <Tooltip.Trigger>
            <Badge variant="outline" class="font-mono text-xs">
              {m.flow_run_evidence_trace_id()}: {traceId}
            </Badge>
          </Tooltip.Trigger>
          <Tooltip.Content>{m.flow_run_evidence_trace_id_tooltip()}</Tooltip.Content>
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
