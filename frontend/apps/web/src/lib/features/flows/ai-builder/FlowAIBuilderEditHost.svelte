<script lang="ts">
  import { onDestroy, untrack } from "svelte";

  import type { Eneo } from "@eneo/eneo-js";

  import FlowAIBuilder from "./FlowAIBuilder.svelte";
  import { initAIBuilderService } from "./FlowAIBuilderService.svelte.ts";

  interface Props {
    eneo: Eneo;
    spaceId: string;
    flowId: string;
    onapplied?: (detail: { flow_id: string; focusStepIndex: number | null }) => void;
  }

  let { eneo, spaceId, flowId, onapplied }: Props = $props();

  const service = untrack(() => initAIBuilderService(eneo, spaceId, flowId));

  onDestroy(() => {
    service.destroy();
  });
</script>

<FlowAIBuilder targetKind="edit" onapplied={(detail) => onapplied?.(detail)} />
