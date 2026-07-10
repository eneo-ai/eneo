<script lang="ts">
  import FlowAIBuilder from "../FlowAIBuilder.svelte";
  import { initAIBuilderService } from "../FlowAIBuilderService.svelte.ts";
  import { initFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import { untrack } from "svelte";
  import type { AIBuilderClientTransport } from "../FlowAIBuilderDriver";
  import type { TargetKind } from "../protocol";

  interface Props {
    transport: AIBuilderClientTransport;
    targetKind?: TargetKind;
    flowId?: string | null;
    initialPrompt?: string | null;
  }

  let { transport, targetKind = "create", flowId = null, initialPrompt = null }: Props = $props();

  initFlowUserMode();
  untrack(() => initAIBuilderService({ client: transport } as never, "space-1", flowId));
</script>

<FlowAIBuilder {targetKind} {initialPrompt} />
