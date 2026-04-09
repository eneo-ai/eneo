<script lang="ts">
  import { Tooltip } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import { Badge, Card } from "@eneo/ui";

  export let runStatusLabel: string;
  export let statusColorClass: string;
  export let traceId: string | null = null;
  export let redactionApplied = false;
</script>

<Card.Root>
  <Card.Content class="flex flex-wrap items-center gap-2 px-4 py-3">
    <span class="{statusColorClass} text-sm font-medium">{runStatusLabel}</span>
    {#if traceId}
      <Tooltip text={m.flow_run_evidence_trace_id_tooltip()}>
        <Badge variant="outline" class="font-mono text-[11px]">
          {m.flow_run_evidence_trace_id()}: {traceId}
        </Badge>
      </Tooltip>
    {/if}
    {#if redactionApplied}
      <Tooltip text={m.flow_run_evidence_redacted_tooltip()}>
        <Badge variant="outline" class="text-[11px]">
          {m.flow_run_evidence_redacted()}
        </Badge>
      </Tooltip>
    {/if}
  </Card.Content>
</Card.Root>
