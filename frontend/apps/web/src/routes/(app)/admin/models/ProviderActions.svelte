<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import type { ModelProviderPublic } from "@intric/intric-js";
  import { IconEllipsis } from "@intric/icons/ellipsis";
  import { Button, Dropdown, Dialog } from "@intric/ui";
  import { getIntric } from "$lib/core/Intric";
  import { invalidate } from "$app/navigation";
  import { writable, type Writable } from "svelte/store";
  import { Plus, Pencil, Trash2 } from "lucide-svelte";
  import ProviderDialog from "./ProviderDialog.svelte";
  import { m } from "$lib/paraglide/messages";

  export let provider: ModelProviderPublic;
  /** Pass this to open AddCompletionModelDialog with this provider pre-selected */
  export let onAddModel: ((providerId: string) => void) | undefined = undefined;

  const intric = getIntric();

  const showEditDialog = writable(false);
  const showDeleteConfirm = writable(false);
  let isDeleting = false;
  let deleteError: string | null = null;

  async function handleDelete() {
    deleteError = null;
    isDeleting = true;
    try {
      await intric.modelProviders.delete({ id: provider.id });
      await invalidate("admin:model-providers:load");
      $showDeleteConfirm = false;
    } catch (e: any) {
      deleteError = e.message || m.failed_to_delete_provider();
    } finally {
      isDeleting = false;
    }
  }
</script>

<Dropdown.Root>
  <Dropdown.Trigger let:trigger asFragment>
    <Button variant="on-fill" is={trigger} padding="icon">
      <IconEllipsis />
    </Button>
  </Dropdown.Trigger>
  <Dropdown.Menu let:item>
    {#if onAddModel}
      <Button
        is={item}
        padding="icon-leading"
        on:click={() => onAddModel?.(provider.id)}
      >
        <Plus class="h-4 w-4" />
        {m.add_model()}
      </Button>
    {/if}
    <Button
      is={item}
      padding="icon-leading"
      on:click={() => {
        $showEditDialog = true;
      }}
    >
      <Pencil class="h-4 w-4" />
      {m.edit_provider()}
    </Button>
    <Button
      is={item}
      padding="icon-leading"
      variant="destructive"
      on:click={() => {
        $showDeleteConfirm = true;
      }}
    >
      <Trash2 class="h-4 w-4" />
      {m.delete_provider()}
    </Button>
  </Dropdown.Menu>
</Dropdown.Root>

<!-- Edit Provider Dialog -->
<ProviderDialog openController={showEditDialog} {provider} />

<!-- Delete Confirmation Dialog -->
<Dialog.Root openController={showDeleteConfirm}>
  <Dialog.Content width="small">
    <Dialog.Title>{m.delete_provider()}</Dialog.Title>
    <Dialog.Section>
      <div class="flex flex-col gap-4 p-4">
        {#if deleteError}
          <div class="border-error bg-error-dimmer text-error-stronger border-l-2 px-4 py-2 text-sm">
            {deleteError}
          </div>
        {/if}
        <p>
          {m.delete_provider_confirm({ name: provider.name })}
        </p>
        <p class="text-muted-foreground text-sm">
          {m.delete_provider_warning()}
        </p>
      </div>
    </Dialog.Section>
    <Dialog.Controls>
      <Button variant="outlined" on:click={() => ($showDeleteConfirm = false)}>
        {m.cancel()}
      </Button>
      <Button
        variant="destructive"
        on:click={handleDelete}
        disabled={isDeleting}
      >
        {isDeleting ? m.deleting() : m.delete_provider()}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
