<svelte:options runes={false} />

<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import type { FlowStep } from "@intric/intric-js";
  import { Button, Dialog } from "@intric/ui";
  import { Separator } from "@eneo/ui";
  import { IconTrash } from "@intric/icons/trash";
  import { m } from "$lib/paraglide/messages";

  export let step: FlowStep;
  export let isPublished: boolean;

  const dispatch = createEventDispatcher<{ removeStep: void }>();

  let showDeleteConfirm: Dialog.OpenState;
</script>

{#if !isPublished}
  <div class="mt-4 pt-4">
    <Separator class="mb-4" />
    <Button
      variant="destructive"
      class="w-full justify-center rounded-lg"
      on:click={() => {
        $showDeleteConfirm = true;
      }}
    >
      <IconTrash size="sm" />
      {m.flow_step_remove()}
    </Button>
  </div>
{/if}

<Dialog.Root alert bind:isOpen={showDeleteConfirm}>
  <Dialog.Content width="small">
    <div class="mb-3 flex justify-center">
      <svg
        class="text-negative-default/60 size-10"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.5"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="8" x2="12" y2="12" />
        <line x1="12" y1="16" x2="12.01" y2="16" />
      </svg>
    </div>
    <Dialog.Title>{m.flow_step_remove()}</Dialog.Title>
    <Dialog.Description>
      {#if step?.output_mode === "template_fill"}
        {m.flow_template_fill_remove_confirm_named({
          name:
            (step.user_description ?? "").trim() ||
            m.flow_step_fallback_label({ order: String(step.step_order) })
        })}
      {:else}
        {m.flow_step_remove_confirm()}
      {/if}
    </Dialog.Description>
    <Dialog.Controls let:close>
      <Button variant="simple" is={close}>{m.cancel()}</Button>
      <Button
        variant="destructive"
        on:click={() => {
          dispatch("removeStep");
          $showDeleteConfirm = false;
        }}>{m.delete()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
