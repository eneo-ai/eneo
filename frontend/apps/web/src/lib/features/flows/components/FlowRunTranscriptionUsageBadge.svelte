<script lang="ts">
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { m } from "$lib/paraglide/messages";
  import {
    buildFlowRunTranscriptionUsageView,
    formatFlowRunAudioDuration,
    type FlowRunTranscriptionUsagePayload
  } from "./flowRunTranscriptionUsage";

  interface Props {
    transcriptionUsage?: FlowRunTranscriptionUsagePayload | null;
  }

  let { transcriptionUsage = null }: Props = $props();

  const usage = $derived.by(() => buildFlowRunTranscriptionUsageView(transcriptionUsage));
</script>

{#if usage.kind === "recorded"}
  <Badge
    variant="outline"
    class="bg-secondary/60 text-muted shrink-0 px-2 py-0.5 text-xs font-medium tabular-nums"
    title={m.flow_run_audio_usage_provider_note()}
  >
    {m.flow_run_audio_badge({ duration: formatFlowRunAudioDuration(usage.audioSeconds) })}
    {#if usage.incomplete}
      <span class="text-warning-stronger">· {m.flow_run_audio_usage_incomplete()}</span>
    {/if}
  </Badge>
{/if}
