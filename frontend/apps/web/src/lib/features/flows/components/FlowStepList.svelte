<script lang="ts">
  import type { FlowStep } from "@intric/intric-js";
  import FlowStepCard from "./FlowStepCard.svelte";
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import { getFlowEditor } from "$lib/features/flows/FlowEditor";
  import { IconPlus } from "@intric/icons/plus";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Separator } from "$lib/components/ui/separator/index.js";
  import { m } from "$lib/paraglide/messages";
  import { parseValidationError } from "$lib/features/flows/flowStepValidationMessages";

  let {
    steps,
    activeStepId,
    isPublished,
    validationErrors = new Map(),
    onBuildWithAI,
    onSelectStep,
    onStepsChanged
  }: {
    steps: FlowStep[];
    activeStepId: string | null;
    isPublished: boolean;
    validationErrors?: Map<string, string[]>;
    onBuildWithAI?: () => void;
    onSelectStep?: (stepId: string | null) => void;
    onStepsChanged?: (steps: FlowStep[]) => void;
  } = $props();

  const mode = getFlowUserMode();
  const flowEditor = getFlowEditor();

  let showRemoveConfirm = $state(false);
  let pendingRemoveIndex: number | null = $state(null);
  let pendingRemoveLabel = $state("");
  let pendingRemoveIsAssembly = $state(false);

  function moveStep(index: number, direction: -1 | 1) {
    const newIndex = index + direction;
    if (newIndex < 0 || newIndex >= steps.length) return;

    const updated = [...steps];
    [updated[index], updated[newIndex]] = [updated[newIndex], updated[index]];

    updated.forEach((step, i) => {
      step.step_order = i + 1;
    });

    onStepsChanged?.(updated);
  }

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
    const orders = new Set<number>();
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

  function confirmRemove() {
    if (pendingRemoveIndex === null) return;
    const updated = steps.filter((_, i) => i !== pendingRemoveIndex);
    updated.forEach((step, i) => {
      step.step_order = i + 1;
    });
    onStepsChanged?.(updated);
    showRemoveConfirm = false;
    pendingRemoveIndex = null;
    pendingRemoveIsAssembly = false;
  }
</script>

<div class="flex h-full flex-col">
  <div class="border-default border-b px-3 py-2">
    <h3 class="text-secondary text-sm font-semibold tracking-wider uppercase">
      {m.flow_steps()} ({steps.length})
    </h3>
  </div>

  <div class="flex-1 overflow-y-auto" role="list" aria-label={m.flow_steps()}>
    {#if steps.length === 0}
      <div class="flex flex-col items-center gap-3 px-4 py-8 text-center">
        <p class="text-secondary text-sm">{m.flow_steps_empty()}</p>
        <p class="text-muted max-w-[200px] text-xs">{m.flow_step_list_empty_hint()}</p>
        {#if !isPublished && onBuildWithAI}
          <div class="mt-2 w-full">
            <Button variant="outline" size="sm" onclick={onBuildWithAI}>
              {m.ai_builder_empty_state_cta()}
            </Button>
          </div>
        {/if}
        {#if !isPublished && $mode === "power_user"}
          <div class="bg-secondary/10 mt-2 w-full rounded-xl px-4 py-4 text-left">
            <p class="text-primary text-sm font-medium">
              {m.flow_template_fill_empty_state_title()}
            </p>
            <p class="text-muted mt-1 text-xs leading-relaxed">
              {m.flow_template_fill_empty_state_body()}
            </p>
            <div class="mt-3">
              <Button
                variant="outline"
                size="sm"
                onclick={() => flowEditor.createTemplateFillStarter()}
              >
                {m.flow_template_fill_empty_state_action()}
              </Button>
            </div>
          </div>
        {/if}
      </div>
    {:else}
      {#each steps as step, index (step.id ?? index)}
        <FlowStepCard
          {step}
          isActive={activeStepId === step.id}
          {isPublished}
          isPowerUser={$mode === "power_user"}
          canMoveUp={index > 0}
          canMoveDown={index < steps.length - 1}
          hasValidationError={stepOrdersWithErrors.has(step.step_order)}
          onClick={() => onSelectStep?.(step.id ?? null)}
          onMoveUp={() => moveStep(index, -1)}
          onMoveDown={() => moveStep(index, 1)}
          onRemove={() => requestRemoveStep(index)}
        />
      {/each}
    {/if}
  </div>

  {#if !isPublished}
    <div class="p-3">
      <Separator class="mb-3" />
      <button
        type="button"
        class="border-default text-secondary hover:border-accent-default hover:bg-accent-dimmer hover:text-accent-default flex w-full items-center justify-center gap-2 rounded-lg border-2 border-dashed py-2.5 text-sm transition-colors"
        onclick={() => flowEditor.addStep()}
      >
        <IconPlus class="size-4" />
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
