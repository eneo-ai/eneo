<script lang="ts">
  import { readable } from "svelte/store";
  import { m } from "$lib/paraglide/messages";
  import FlowGraph from "$lib/features/flows/components/FlowGraph.svelte";
  import { type FlowUserMode } from "$lib/features/flows/FlowUserMode";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import { draftSpecToFlow } from "./aiBuilderDraftFlow";
  import type { FlowDraftSpecCore } from "./protocol";

  interface Props {
    spec: FlowDraftSpecCore;
    isStreaming?: boolean;
  }
  let { spec, isStreaming = false }: Props = $props();

  // The builder canvas is comprehension-first and read-only: it always renders in
  // user mode and supplies a no-op assistant source, so FlowGraph never reaches
  // for the flow-editor context that only exists on the editor page.
  const userMode = readable<FlowUserMode>("user");
  const draftAssistants = {
    assistantRevision: readable(0),
    loadAssistant: async (): Promise<unknown> => null
  };

  const flow = $derived(draftSpecToFlow(spec));
  const hasSteps = $derived(flow.steps.length > 0);
</script>

{#if hasSteps}
  <div class="h-[340px] w-full md:h-[420px]">
    <FlowGraph
      {flow}
      mode={userMode}
      assistantSource={draftAssistants}
      activeStepId={null}
      autoFit
      direction="TB"
    />
  </div>
{:else if isStreaming}
  <div
    class="flex h-[340px] w-full flex-col justify-center gap-4 px-6 md:h-[420px]"
    aria-hidden="true"
  >
    <div class="flex items-center gap-3">
      <Skeleton class="h-12 w-28 rounded-lg" />
      <Skeleton class="h-px flex-1" />
      <Skeleton class="h-12 w-28 rounded-lg" />
      <Skeleton class="h-px flex-1" />
      <Skeleton class="h-12 w-28 rounded-lg" />
    </div>
    <p class="text-secondary text-center text-xs">{m.ai_builder_canvas_assembling()}</p>
  </div>
{:else}
  <div
    class="text-secondary flex h-[340px] w-full items-center justify-center px-6 text-center text-sm md:h-[420px]"
  >
    {m.flow_graph_empty()}
  </div>
{/if}
