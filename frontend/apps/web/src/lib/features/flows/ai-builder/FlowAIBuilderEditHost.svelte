<script lang="ts">
  import { onDestroy } from "svelte";

  import type { Intric } from "@intric/intric-js";

  import FlowAIBuilder from "./FlowAIBuilder.svelte";
  import { initAIBuilderService } from "./FlowAIBuilderService.svelte.ts";

  interface Props {
    intric: Intric;
    spaceId: string;
    flowId: string;
    onapplied?: (detail: { flow_id: string }) => void;
  }

  let { intric, spaceId, flowId, onapplied }: Props = $props();

  const service = initAIBuilderService(intric, spaceId, flowId);

  onDestroy(() => {
    service.destroy();
  });
</script>

<FlowAIBuilder
  targetKind="edit"
  onapplied={(detail) => onapplied?.(detail)}
/>
