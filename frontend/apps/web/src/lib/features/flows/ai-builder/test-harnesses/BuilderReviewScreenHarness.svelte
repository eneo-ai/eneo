<script lang="ts">
  import { initSpacesManager } from "$lib/features/spaces/SpacesManager";
  import type { Space } from "@eneo/eneo-js";
  import { untrack, type ComponentProps } from "svelte";
  import type { AIBuilderClientTransport, FlowAIBuilderState } from "../FlowAIBuilderDriver";
  import BuilderReviewScreen from "../BuilderReviewScreen.svelte";
  import { initAIBuilderService } from "../FlowAIBuilderService.svelte.ts";

  interface Props {
    currentSpace: Pick<Space, "completion_models" | "transcription_models"> & Partial<Space>;
    state: Partial<FlowAIBuilderState>;
    transport?: AIBuilderClientTransport;
    /** Render-time props forwarded to the screen, typed by the component. */
    screenProps?: Partial<ComponentProps<typeof BuilderReviewScreen>>;
    /** Test hook: receive the service instance to drive live state changes. */
    onservice?: (service: ReturnType<typeof initAIBuilderService>) => void;
  }

  let {
    currentSpace,
    state,
    screenProps = {},
    onservice,
    transport = {
      fetch: async () => {
        throw new Error("Unexpected AI Builder fetch in review screen harness.");
      },
      stream: async () => {
        throw new Error("Unexpected AI Builder stream in review screen harness.");
      }
    }
  }: Props = $props();

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
  // svelte-ignore state_referenced_locally
  onservice?.(service);
</script>

<BuilderReviewScreen {...screenProps} />
