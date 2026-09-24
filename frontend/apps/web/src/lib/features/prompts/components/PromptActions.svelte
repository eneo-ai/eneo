<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconTrash } from "@eneo/icons/trash";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { getPromptManager } from "../PromptManager";
  import type { PromptSparse } from "@eneo/eneo-js";
  import { IconInfo } from "@eneo/icons/info";
  import { m } from "$lib/paraglide/messages";

  export let prompt: PromptSparse;
  let showDeleteDialog = false;

  const {
    state: { previewedPrompt },
    deletePrompt,
    loadPreview
  } = getPromptManager();

  $: isPromptPreviewed = prompt.id === $previewedPrompt?.id;

  $: description =
    prompt.description && prompt.description.length > 50
      ? prompt.description?.substring(0, 45) + "..."
      : prompt.description;
</script>

<button
  on:click={() => loadPreview({ id: prompt.id })}
  class="absolute inset-0"
  data-prompt-previewed={isPromptPreviewed}
  aria-label={m.open_this_prompt_in_preview_panel()}
></button>

<div class="flex w-full items-center justify-end gap-2">
  {#if description}
    <Tooltip.Root>
      <Tooltip.Trigger class="text-accent-stronger pointer-events-auto z-[1000] cursor-default">
        <IconInfo></IconInfo>
        <span class="sr-only">{description}</span>
      </Tooltip.Trigger>
      <Tooltip.Content>{description}</Tooltip.Content>
    </Tooltip.Root>
  {/if}
  <DropdownMenu.Root>
    <DropdownMenu.Trigger>
      {#snippet child({ props })}
        <Button {...props} variant="ghost" size="icon" aria-label={m.actions()}>
          <IconEllipsis />
        </Button>
      {/snippet}
    </DropdownMenu.Trigger>
    <DropdownMenu.Content align="end">
      <DropdownMenu.Item
        variant="destructive"
        disabled={prompt.is_selected}
        onSelect={() => {
          showDeleteDialog = true;
        }}
        aria-label={m.delete_prompt()}
      >
        <IconTrash size="sm" />{m.delete()}
      </DropdownMenu.Item>
    </DropdownMenu.Content>
  </DropdownMenu.Root>

  <ConfirmDialog
    bind:open={showDeleteDialog}
    title={m.delete_prompt()}
    description={m.do_you_really_want_to_delete_this_version()}
    confirmLabel={m.delete()}
    pendingLabel={m.deleting()}
    onConfirm={() => deletePrompt(prompt)}
  />
</div>

<style lang="postcss">
  @reference "@eneo/ui/styles";
  button[data-prompt-previewed="true"] {
    @apply bg-accent-dimmer pointer-events-none z-[-1] mix-blend-multiply;
  }
</style>
