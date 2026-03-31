<script lang="ts">
  import { Tooltip } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  export let runStatusLabel: string;
  export let statusColorClass: string;
  export let traceId: string | null = null;
  export let redactionApplied = false;
</script>

<div class="border-default bg-primary flex flex-wrap items-center gap-2 rounded-lg border px-4 py-3">
  <span class="{statusColorClass} text-sm font-medium">{runStatusLabel}</span>
  {#if traceId}
    <Tooltip text={m.flow_run_evidence_trace_id_tooltip()}>
      <span class="border-default bg-hover-dimmer rounded-md border px-2 py-1 font-mono text-[11px]">
        {m.flow_run_evidence_trace_id()}: {traceId}
      </span>
    </Tooltip>
  {/if}
  {#if redactionApplied}
    <Tooltip text={m.flow_run_evidence_redacted_tooltip()}>
      <span class="border-default bg-hover-dimmer rounded-md border px-2 py-1 text-[11px]">
        {m.flow_run_evidence_redacted()}
      </span>
    </Tooltip>
  {/if}
</div>
