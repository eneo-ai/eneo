<script lang="ts">
  import type { FlowStep } from "@intric/intric-js";
  import FlowStepCard from "./FlowStepCard.svelte";
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import { getFlowEditor } from "$lib/features/flows/FlowEditor";
  import { IconPlus } from "@intric/icons/plus";
  import { Button, Dialog } from "@intric/ui";
  import { createEventDispatcher } from "svelte";
  import { m } from "$lib/paraglide/messages";

  export let steps: FlowStep[];
  export let activeStepId: string | null;
  export let isPublished: boolean;

  const dispatch = createEventDispatcher<{
    selectStep: string | null;
    stepsChanged: FlowStep[];
  }>();

  const mode = getFlowUserMode();
  const flowEditor = getFlowEditor();

  let showRemoveConfirm: Dialog.OpenState;
  let pendingRemoveIndex: number | null = null;
  let pendingRemoveLabel = "";
  let pendingRemoveIsAssembly = false;

  function moveStep(index: number, direction: -1 | 1) {
    const newIndex = index + direction;
    if (newIndex < 0 || newIndex >= steps.length) return;

    const updated = [...steps];
    [updated[index], updated[newIndex]] = [updated[newIndex], updated[index]];

    // Renumber step_order contiguously
    updated.forEach((step, i) => {
      step.step_order = i + 1;
    });

    dispatch("stepsChanged", updated);
  }

  function requestRemoveStep(index: number) {
    const targetStep = steps[index];
    pendingRemoveIndex = index;
    pendingRemoveIsAssembly = targetStep?.output_mode === "template_fill";
    pendingRemoveLabel =
      (targetStep?.user_description ?? "").trim() ||
      m.flow_step_fallback_label({ order: String(targetStep?.step_order ?? index + 1) });
    $showRemoveConfirm = true;
  }

  function confirmRemove() {
    if (pendingRemoveIndex === null) return;
    const updated = steps.filter((_, i) => i !== pendingRemoveIndex);
    updated.forEach((step, i) => {
      step.step_order = i + 1;
    });
    dispatch("stepsChanged", updated);
    $showRemoveConfirm = false;
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
                variant="outlined"
                size="small"
                on:click={() => flowEditor.createTemplateFillStarter()}
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
          on:click={() => dispatch("selectStep", step.id ?? null)}
          on:moveUp={() => moveStep(index, -1)}
          on:moveDown={() => moveStep(index, 1)}
          on:remove={() => requestRemoveStep(index)}
        />
      {/each}
    {/if}
  </div>

  {#if !isPublished}
    <div class="border-default border-t p-3">
      <button
        type="button"
        class="border-default text-secondary hover:border-accent-default hover:bg-accent-dimmer hover:text-accent-default flex w-full items-center justify-center gap-2 rounded-lg border-2 border-dashed py-2.5 text-sm transition-colors"
        on:click={() => flowEditor.addStep()}
      >
        <IconPlus class="size-4" />
        {m.flow_step_add()}
      </button>
    </div>
  {/if}
</div>

<Dialog.Root alert bind:isOpen={showRemoveConfirm}>
  <Dialog.Content width="small">
    <Dialog.Title>{m.flow_step_remove()}</Dialog.Title>
    <Dialog.Description>
      {#if pendingRemoveIsAssembly}
        {m.flow_template_fill_remove_confirm_named({ name: pendingRemoveLabel })}
      {:else}
        {m.flow_step_remove_confirm_named({ name: pendingRemoveLabel })}
      {/if}
    </Dialog.Description>
    <Dialog.Controls let:close>
      <Button is={close} variant="outlined">{m.cancel()}</Button>
      <Button variant="destructive" on:click={confirmRemove}>{m.delete()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
