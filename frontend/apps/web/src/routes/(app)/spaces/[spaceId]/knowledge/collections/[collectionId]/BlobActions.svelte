<script lang="ts">
  import { IconTrash } from "@eneo/icons/trash";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import NameDialog from "$lib/components/NameDialog.svelte";
  import { invalidate } from "$app/navigation";
  import { getEneo } from "$lib/core/Eneo";
  import type { InfoBlob } from "@eneo/eneo-js";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { IconEdit } from "@eneo/icons/edit";
  import { m } from "$lib/paraglide/messages";

  const eneo = getEneo();
  export let blob: InfoBlob;
  export let canEdit: boolean;

  async function updateBlobName(title: string) {
    await eneo.infoBlobs.update({
      blob: { id: blob.id },
      update: { metadata: { title } }
    });
    invalidate("blobs:list");
  }

  async function deleteBlob() {
    await eneo.infoBlobs.delete(blob);
    invalidate("blobs:list");
  }

  let showDeleteDialog = false;
  let showEditDialog = false;
</script>

{#if canEdit}
  <DropdownMenu.Root>
    <DropdownMenu.Trigger>
      {#snippet child({ props })}
        <Button {...props} variant="ghost" size="icon" aria-label={m.actions()}>
          <IconEllipsis />
        </Button>
      {/snippet}
    </DropdownMenu.Trigger>

    <DropdownMenu.Content align="end">
      <DropdownMenu.Item onSelect={() => (showEditDialog = true)}>
        <IconEdit size="sm" />
        {m.edit()}
      </DropdownMenu.Item>
      <DropdownMenu.Item variant="destructive" onSelect={() => (showDeleteDialog = true)}>
        <IconTrash size="sm" />{m.delete()}
      </DropdownMenu.Item>
    </DropdownMenu.Content>
  </DropdownMenu.Root>
{/if}

<NameDialog
  bind:open={showEditDialog}
  title={m.edit_file()}
  description={m.enter_new_file_name()}
  label={m.name()}
  initial={blob.metadata.title ?? ""}
  submitLabel={m.save_changes()}
  pendingLabel={m.saving()}
  errorContext={(title) => m.could_not_change_title_to({ title })}
  onSubmit={updateBlobName}
/>

<ConfirmDialog
  bind:open={showDeleteDialog}
  title={m.delete_file()}
  description={m.confirm_delete_file({ fileName: blob.metadata.title || "" })}
  confirmLabel={m.delete()}
  errorContext={m.could_not_delete_file({ fileName: blob.metadata.title ?? m.this_file() })}
  onConfirm={deleteBlob}
/>
