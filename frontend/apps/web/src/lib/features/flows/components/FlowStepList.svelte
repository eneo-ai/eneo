<script lang="ts">
  import type { FlowStep } from "@eneo/eneo-js";
  import FlowStepCard from "./FlowStepCard.svelte";
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import { getFlowEditor, type FlowStepCreationSeed } from "$lib/features/flows/FlowEditor";
  import { IconPlus } from "@eneo/icons/plus";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Separator } from "$lib/components/ui/separator/index.js";
  import { m } from "$lib/paraglide/messages";
  import { SvelteSet } from "svelte/reactivity";
  import { parseValidationError } from "$lib/features/flows/flowStepValidationMessages";
  import FlowAddStepDialog from "./FlowAddStepDialog.svelte";

  let {
    steps,
    activeStepId,
    isPublished,
    validationErrors = new Map(),
    onSelectStep,
    onMoveStep,
    onRemoveStep
  }: {
    steps: FlowStep[];
    activeStepId: string | null;
    isPublished: boolean;
    validationErrors?: Map<string, string[]>;
    onSelectStep?: (stepId: string | null) => void;
    onMoveStep?: (index: number, direction: -1 | 1) => void | Promise<void>;
    onRemoveStep?: (index: number) => void | Promise<void>;
  } = $props();

  const mode = getFlowUserMode();
  const flowEditor = getFlowEditor();

  let showAddStep = $state(false);
  const previousOutputType = $derived(
    steps.length > 0 ? steps[steps.length - 1].output_type : null
  );
  function handleAddFromTemplate(seed: FlowStepCreationSeed | null) {
    void flowEditor.addStep(seed ?? undefined);
  }

  let showRemoveConfirm = $state(false);
  let pendingRemoveIndex: number | null = $state(null);
  let pendingRemoveLabel = $state("");
  let pendingRemoveIsAssembly = $state(false);

  function requestRemoveStep(index: number) {
    const targetStep = steps[index];
    pendingRemoveIndex = index;
    pendingRemoveIsAssembly = targetStep?.output_mode === "template_fill";
    pendingRemoveLabel =
      (targetStep?.user_description ?? "").trim() ||
      m.flow_step_fallback_label({ order: String(targetStep?.step_order ?? index + 1) });
    showRemoveConfirm = true;
  }

  const stepOrdersWithErrors = $derived.by(() => {
    const orders = new SvelteSet<number>();
    for (const [key, values] of validationErrors.entries()) {
      const parsed = parseValidationError(key, values);
      if (!parsed) continue;
      if (parsed.kind === "step") {
        orders.add(parsed.stepOrder);
      } else if (parsed.kind === "assistant") {
        const step = steps.find((s) => s.assistant_id === parsed.assistantId);
        if (step) orders.add(step.step_order);
      }
    }
    return orders;
  });

  async function confirmRemove() {
    if (pendingRemoveIndex === null) return;
    await onRemoveStep?.(pendingRemoveIndex);
    showRemoveConfirm = false;
    pendingRemoveIndex = null;
    pendingRemoveIsAssembly = false;
  }
</script>

<div class="flex h-full flex-col">
  <div
    class="border-default bg-secondary/30 flex items-center justify-between border-b px-3.5 py-2.5"
  >
    <h2 class="text-secondary text-[0.8125rem] font-medium">
      {m.flow_steps()}
    </h2>
    <span
      class="text-muted bg-primary/70 border-default rounded-full border px-1.5 py-0.5 text-xs leading-none font-semibold tabular-nums"
    >
      {steps.length}
    </span>
  </div>

  <div class="flex-1 overflow-y-auto" role="list" aria-label={m.flow_steps()}>
    {#if steps.length === 0}
      <div class="flex flex-col items-center px-4 py-8 text-center">
        <p class="text-secondary text-sm">{m.flow_steps_empty()}</p>
      </div>
    {:else}
      {#each steps as step, index (step.id ?? index)}
        <FlowStepCard
          {step}
          {index}
          isActive={activeStepId === step.id}
          {isPublished}
          isPowerUser={$mode === "power_user"}
          canMoveUp={index > 0}
          canMoveDown={index < steps.length - 1}
          hasValidationError={stepOrdersWithErrors.has(step.step_order)}
          onClick={() => onSelectStep?.(step.id ?? null)}
          onMoveUp={() => void onMoveStep?.(index, -1)}
          onMoveDown={() => void onMoveStep?.(index, 1)}
          onRemove={() => requestRemoveStep(index)}
        />
      {/each}
    {/if}
  </div>

  {#if !isPublished && steps.length > 0}
    <div class="px-3 pt-2 pb-3">
      <Separator class="mb-3" />
      <button
        type="button"
        class="border-default text-secondary hover:border-accent-default hover:bg-accent-dimmer/60 hover:text-accent-default focus-visible:ring-accent-default/30 flex min-h-[40px] w-full items-center justify-center gap-2 rounded-xl border border-dashed py-2.5 text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:outline-none"
        onclick={() => (showAddStep = true)}
      >
        <IconPlus class="size-4" aria-hidden="true" />
        {m.flow_step_add()}
      </button>
    </div>
  {/if}
</div>

<AlertDialog.Root bind:open={showRemoveConfirm}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.flow_step_remove()}</AlertDialog.Title>
      <AlertDialog.Description>
        {#if pendingRemoveIsAssembly}
          {m.flow_template_fill_remove_confirm_named({ name: pendingRemoveLabel })}
        {:else}
          {m.flow_step_remove_confirm_named({ name: pendingRemoveLabel })}
        {/if}
      </AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action variant="destructive" onclick={confirmRemove}
        >{m.delete()}</AlertDialog.Action
      >
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>

<FlowAddStepDialog bind:open={showAddStep} {previousOutputType} onConfirm={handleAddFromTemplate} />
