<script lang="ts">
  import type { FlowStep } from "@eneo/eneo-js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { IconTrash } from "@eneo/icons/trash";
  import { m } from "$lib/paraglide/messages";

  let {
    step,
    isPublished,
    onRemoveStep
  }: {
    step: FlowStep;
    isPublished: boolean;
    onRemoveStep?: () => void;
  } = $props();

  let showDeleteConfirm = $state(false);
</script>

{#if !isPublished}
  <div class="mt-6 flex justify-center pb-2">
    <button
      type="button"
      class="text-muted hover:text-negative-stronger inline-flex items-center gap-1.5 text-sm transition-colors"
      onclick={() => {
        showDeleteConfirm = true;
      }}
    >
      <IconTrash class="size-3.5" />
      {m.flow_step_remove()}
    </button>
  </div>
{/if}

<AlertDialog.Root bind:open={showDeleteConfirm}>
  <AlertDialog.Content>
    <AlertDialog.Header>
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
      <AlertDialog.Title>{m.flow_step_remove()}</AlertDialog.Title>
      <AlertDialog.Description>
        {#if step?.output_mode === "template_fill"}
          {m.flow_template_fill_remove_confirm_named({
            name:
              (step.user_description ?? "").trim() ||
              m.flow_step_fallback_label({ order: String(step.step_order) })
          })}
        {:else}
          {m.flow_step_remove_confirm()}
        {/if}
      </AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action variant="destructive" onclick={() => onRemoveStep?.()}>
        {m.delete()}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
