<script lang="ts">
  import type { FlowStep } from "@intric/intric-js";
  import FlowStepCard from "./FlowStepCard.svelte";
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import { getFlowEditor } from "$lib/features/flows/FlowEditor";
  import { IconPlus } from "@intric/icons/plus";
  import { Button } from "@intric/ui";
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

  // --- DnD state ---
  let draggedIndex: number | null = null;
  let dropTargetIndex: number | null = null;

  function fixFirstStepInputSource(updated: FlowStep[]): FlowStep[] {
    if (updated[0] && (updated[0].input_source === "previous_step" || updated[0].input_source === "all_previous_steps")) {
      updated[0] = { ...updated[0], input_source: "flow_input" };
    }
    return updated;
  }

  function moveStep(index: number, direction: -1 | 1) {
    const newIndex = index + direction;
    if (newIndex < 0 || newIndex >= steps.length) return;

    const updated = [...steps];
    [updated[index], updated[newIndex]] = [updated[newIndex], updated[index]];

    // Renumber step_order contiguously
    updated.forEach((step, i) => {
      step.step_order = i + 1;
    });

    dispatch("stepsChanged", fixFirstStepInputSource(updated));
  }

  function reorderStep(fromIndex: number, toIndex: number) {
    if (fromIndex === toIndex) return;

    const updated = [...steps];
    const [moved] = updated.splice(fromIndex, 1);
    updated.splice(toIndex, 0, moved);

    updated.forEach((step, i) => {
      step.step_order = i + 1;
    });

    dispatch("stepsChanged", fixFirstStepInputSource(updated));
  }

  function removeStep(index: number) {
    const updated = steps.filter((_, i) => i !== index);
    updated.forEach((step, i) => {
      step.step_order = i + 1;
    });
    dispatch("stepsChanged", fixFirstStepInputSource(updated));
  }

  // --- DnD handlers ---
  function handleDragStart(e: CustomEvent<number>) {
    draggedIndex = e.detail;
  }

  function handleDragEnd() {
    draggedIndex = null;
    dropTargetIndex = null;
  }

  function handleDragOver(e: DragEvent) {
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
    if (draggedIndex === null) return;

    const list = (e.currentTarget as HTMLElement);
    const cards = Array.from(list.querySelectorAll("[role='option']"));
    const mouseY = e.clientY;

    let targetIdx = cards.length;
    for (let i = 0; i < cards.length; i++) {
      const rect = cards[i].getBoundingClientRect();
      if (mouseY < rect.top + rect.height / 2) {
        targetIdx = i;
        break;
      }
    }

    // Adjust for the dragged item's original position
    dropTargetIndex = targetIdx;
  }

  function handleDrop(e: DragEvent) {
    e.preventDefault();
    if (draggedIndex === null || dropTargetIndex === null) return;

    let toIndex = dropTargetIndex;
    // If dropping below the original position, adjust for the removed item
    if (toIndex > draggedIndex) toIndex--;
    if (toIndex !== draggedIndex) {
      reorderStep(draggedIndex, toIndex);
    }

    draggedIndex = null;
    dropTargetIndex = null;
  }

  function handleDragLeave(e: DragEvent) {
    // Only clear when leaving the list itself, not child elements
    const related = e.relatedTarget as Node | null;
    if (related && (e.currentTarget as HTMLElement).contains(related)) return;
    dropTargetIndex = null;
  }
</script>

<div class="flex h-full flex-col">
  <div class="border-default border-b px-3 py-2">
    <h3 class="text-xs font-semibold uppercase tracking-wider text-secondary">
      {m.flow_steps()} ({steps.length})
    </h3>
  </div>

  <div
    class="flex-1 overflow-y-auto"
    role="listbox"
    aria-label={m.flow_steps()}
    on:dragover={handleDragOver}
    on:drop={handleDrop}
    on:dragleave={handleDragLeave}
  >
    {#if steps.length === 0}
      <div class="flex flex-col items-center gap-3 px-4 py-8 text-center">
        <p class="text-secondary text-sm">{m.flow_steps_empty()}</p>
        {#if !isPublished}
          <Button variant="primary" on:click={() => flowEditor.addStep()}>
            {m.flow_empty_add_step()}
          </Button>
        {/if}
      </div>
    {:else}
      {#each steps as step, index (step.id ?? index)}
        <!-- Drop indicator line -->
        {#if draggedIndex !== null && dropTargetIndex === index && dropTargetIndex !== draggedIndex && dropTargetIndex !== draggedIndex + 1}
          <div class="h-0.5 bg-blue-400 mx-2 rounded-full transition-all duration-100"></div>
        {/if}

        <FlowStepCard
          {step}
          {index}
          isActive={activeStepId === step.id}
          {isPublished}
          isPowerUser={$mode === "power_user"}
          canMoveUp={index > 0}
          canMoveDown={index < steps.length - 1}
          isDragging={draggedIndex === index}
          on:click={() => dispatch("selectStep", step.id ?? null)}
          on:moveUp={() => moveStep(index, -1)}
          on:moveDown={() => moveStep(index, 1)}
          on:remove={() => removeStep(index)}
          on:dragstart={handleDragStart}
          on:dragend={handleDragEnd}
        />
      {/each}

      <!-- Drop indicator at the end -->
      {#if draggedIndex !== null && dropTargetIndex === steps.length && dropTargetIndex !== draggedIndex + 1}
        <div class="h-0.5 bg-blue-400 mx-2 rounded-full transition-all duration-100"></div>
      {/if}
    {/if}
  </div>

  {#if !isPublished}
    <div class="border-default border-t p-3">
      <Button variant="outlined" class="w-full justify-center hover:border-blue-300 hover:text-blue-600 transition-colors duration-200" on:click={() => flowEditor.addStep()}>
        <IconPlus size="sm" />
        {m.flow_step_add()}
      </Button>
    </div>
  {/if}
</div>
