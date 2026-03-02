<script lang="ts">
  import type { Intric, FlowStep } from "@intric/intric-js";
  import { Button } from "@intric/ui";
  import { createEventDispatcher } from "svelte";
  import { m } from "$lib/paraglide/messages";

  export let flowId: string;
  export let publishedVersion: number | null | undefined;
  export let currentStep: FlowStep;
  export let intric: Intric;

  const dispatch = createEventDispatcher<{ restore: string }>();

  let isExpanded = false;
  let previousPrompt: string | null = null;
  let loading = false;

  async function loadPreviousVersion() {
    if (!publishedVersion || !flowId) return;
    loading = true;
    try {
      // Fetch the graph for the published version to get the definition
      // The version snapshot is embedded in the evidence endpoint
      // For now, we use the graph endpoint which reflects the live state
      // TODO: Add a versions endpoint to intric-js
      const graph = await intric.flows.graph({ id: flowId });
      const matchingNode = graph.nodes?.find(
        (n: any) => n.step_order === currentStep.step_order && n.type === "llm"
      );
      previousPrompt = matchingNode ? "Previous version prompt not yet available" : null;
    } catch {
      previousPrompt = null;
    }
    loading = false;
  }

  function handleRestore() {
    if (previousPrompt) {
      dispatch("restore", previousPrompt);
    }
  }
</script>

{#if publishedVersion != null}
  <div class="mt-2">
    <button
      class="text-secondary hover:text-primary text-xs underline"
      on:click={() => {
        isExpanded = !isExpanded;
        if (isExpanded && previousPrompt === null) loadPreviousVersion();
      }}
    >
      {m.flow_prompt_revert()}
    </button>

    {#if isExpanded}
      <div class="bg-hover-dimmer mt-2 rounded-lg p-3">
        {#if loading}
          <p class="text-secondary text-xs">{m.flow_loading()}</p>
        {:else if previousPrompt}
          <pre class="mb-2 whitespace-pre-wrap text-xs">{previousPrompt}</pre>
          <Button variant="outlined"  on:click={handleRestore}>
            {m.flow_prompt_restore()}
          </Button>
        {:else}
          <p class="text-secondary text-xs">{m.flow_prompt_no_previous()}</p>
        {/if}
      </div>
    {/if}
  </div>
{/if}
