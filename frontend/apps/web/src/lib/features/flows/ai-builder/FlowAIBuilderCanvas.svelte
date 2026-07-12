<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import type { FlowDraftSpecCore } from "./protocol";

  interface Props {
    spec: FlowDraftSpecCore;
    isStreaming?: boolean;
  }
  let { spec, isStreaming = false }: Props = $props();

  const steps = $derived(spec.steps);
  const hasSteps = $derived(steps.length > 0);
</script>

{#if hasSteps}
  <div class="bg-secondary/15 flex h-[340px] w-full overflow-y-auto px-4 py-5 md:h-[420px] md:px-6">
    <ol
      class="mx-auto flex w-full max-w-[480px] flex-col items-stretch"
      data-testid="ai-builder-draft-canvas"
      aria-label={m.flow_steps()}
    >
      {#each steps as step, index (step.plan_step_ref)}
        <li class="flex flex-col items-center">
          <div
            class="border-default bg-primary flex min-h-14 w-full items-center gap-3 rounded-lg border px-4 py-3"
            data-testid="ai-builder-draft-step"
            data-step-ref={step.plan_step_ref}
          >
            <span
              class="bg-accent-dimmer text-accent-stronger flex size-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold tabular-nums"
            >
              {index + 1}
            </span>
            <span class="text-primary min-w-0 text-sm leading-snug font-medium break-words">
              {step.name}
            </span>
          </div>
          {#if index < steps.length - 1}
            <div
              class="border-default h-7 w-px shrink-0 border-l"
              data-testid="ai-builder-draft-edge"
              aria-hidden="true"
            ></div>
          {/if}
        </li>
      {/each}
    </ol>
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
