<script lang="ts">
  import { initSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { initFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import type { Space } from "@eneo/eneo-js";
  import { untrack } from "svelte";
  import type { AIBuilderClientTransport, FlowAIBuilderState } from "../FlowAIBuilderDriver";
  import FlowAIBuilderPlanPane from "../FlowAIBuilderPlanPane.svelte";
  import { initAIBuilderService } from "../FlowAIBuilderService.svelte.ts";

  interface Props {
    currentSpace: Pick<Space, "completion_models" | "transcription_models"> & Partial<Space>;
    state: Partial<FlowAIBuilderState>;
    transport?: AIBuilderClientTransport;
    /** Enkel ("user", default) or Avancerad ("power_user"). */
    userMode?: "user" | "power_user";
  }

  let {
    currentSpace,
    state,
    userMode = "user",
    transport = {
      fetch: async () => {
        throw new Error("Unexpected AI Builder fetch in plan pane harness.");
      },
      stream: async () => {
        throw new Error("Unexpected AI Builder stream in plan pane harness.");
      }
    }
  }: Props = $props();

  const mode = initFlowUserMode();
  untrack(() => mode.set(userMode));

  const service = untrack(() => {
    const spacesManagerParams: Parameters<typeof initSpacesManager>[0] = {
      spaces: [],
      currentSpace: currentSpace as unknown as Space,
      eneo: {} as Parameters<typeof initSpacesManager>[0]["eneo"]
    };
    initSpacesManager(spacesManagerParams);

    const eneo: Parameters<typeof initAIBuilderService>[0] = {
      client: transport
    } as Parameters<typeof initAIBuilderService>[0];
    return initAIBuilderService(eneo, "space-1", null);
  });

  untrack(() => service.seedState(state));
</script>

<FlowAIBuilderPlanPane />
