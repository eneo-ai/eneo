<script lang="ts">
  import type { Intric, FlowStep } from "@intric/intric-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import * as Card from "$lib/components/ui/card/index.js";

  let {
    flowId,
    publishedVersion,
    currentStep,
    intric,
    onRestore
  }: {
    flowId: string;
    publishedVersion: number | null | undefined;
    currentStep: FlowStep;
    intric: Intric;
    onRestore?: (prompt: string) => void;
  } = $props();

  let isExpanded = $state(false);
  let previousPrompt: string | null = $state(null);
  let loading = $state(false);

  async function loadPreviousVersion() {
    if (!publishedVersion || !flowId) return;
    loading = true;
    try {
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
      onRestore?.(previousPrompt);
    }
  }
</script>

{#if publishedVersion != null}
  <div class="mt-2">
    <button
      class="text-secondary hover:text-primary text-xs underline"
      onclick={() => {
        isExpanded = !isExpanded;
        if (isExpanded && previousPrompt === null) loadPreviousVersion();
      }}
    >
      {m.flow_prompt_revert()}
    </button>

    {#if isExpanded}
      <Card.Root class="mt-2">
        <Card.Content class="p-3">
          {#if loading}
            <p class="text-secondary text-xs">{m.flow_loading()}</p>
          {:else if previousPrompt}
            <pre class="mb-2 text-xs whitespace-pre-wrap">{previousPrompt}</pre>
            <Button variant="outline" onclick={handleRestore}>
              {m.flow_prompt_restore()}
            </Button>
          {:else}
            <p class="text-secondary text-xs">{m.flow_prompt_no_previous()}</p>
          {/if}
        </Card.Content>
      </Card.Root>
    {/if}
  </div>
{/if}
