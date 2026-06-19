<script lang="ts">
  import { initSpacesManager } from "$lib/features/spaces/SpacesManager";
  import type { Space } from "@intric/intric-js";
  import { untrack } from "svelte";
  import type { AIBuilderClientTransport, FlowAIBuilderState } from "../FlowAIBuilderDriver";
  import FlowAIBuilderPlanPane from "../FlowAIBuilderPlanPane.svelte";
  import { initAIBuilderService } from "../FlowAIBuilderService.svelte.ts";

  interface Props {
    currentSpace: Pick<Space, "completion_models" | "transcription_models"> & Partial<Space>;
    state: Partial<FlowAIBuilderState>;
    transport?: AIBuilderClientTransport;
  }

  let {
    currentSpace,
    state,
    transport = {
      fetch: async () => {
        throw new Error("Unexpected AI Builder fetch in plan pane harness.");
      },
      stream: async () => {
        throw new Error("Unexpected AI Builder stream in plan pane harness.");
      }
    }
  }: Props = $props();

  const service = untrack(() => {
    const spacesManagerParams: Parameters<typeof initSpacesManager>[0] = {
      spaces: [],
      currentSpace: currentSpace as unknown as Space,
      intric: {} as Parameters<typeof initSpacesManager>[0]["intric"]
    };
    initSpacesManager(spacesManagerParams);

    const intric: Parameters<typeof initAIBuilderService>[0] = {
      client: transport
    } as Parameters<typeof initAIBuilderService>[0];
    return initAIBuilderService(intric, "space-1", null);
  });

  untrack(() => service.seedState(state));
</script>

<FlowAIBuilderPlanPane />
