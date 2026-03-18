<script lang="ts">
  import FlowAIBuilder from "../FlowAIBuilder.svelte";
  import { initAIBuilderService } from "../FlowAIBuilderService.svelte.ts";
  import type { AIBuilderClientTransport } from "../FlowAIBuilderDriver";
  import type { TargetKind } from "../protocol";

  interface Props {
    transport: AIBuilderClientTransport;
    targetKind?: TargetKind;
    flowId?: string | null;
  }

  let { transport, targetKind = "create", flowId = null }: Props = $props();

  initAIBuilderService({ client: transport } as never, "space-1", flowId);
</script>

<FlowAIBuilder {targetKind} />
