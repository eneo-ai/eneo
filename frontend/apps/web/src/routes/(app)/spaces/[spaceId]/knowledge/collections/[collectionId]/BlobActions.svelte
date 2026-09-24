<script lang="ts">
  import { IconTrash } from "@eneo/icons/trash";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import { useId } from "bits-ui";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { invalidate } from "$app/navigation";
  import { getEneo } from "$lib/core/Eneo";
  import type { InfoBlob } from "@eneo/eneo-js";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { IconEdit } from "@eneo/icons/edit";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";

  const eneo = getEneo();
  export let blob: InfoBlob;
  export let canEdit: boolean;

  let updatableTitle = blob.metadata.title ?? "";
  const titleId = useId();
  async function updateBlobName() {
    try {
      await eneo.infoBlobs.update({
        blob: { id: blob.id },
        update: { metadata: { title: updatableTitle } }
      });
      invalidate("blobs:list");
      return true;
    } catch (e) {
      toastError(e, m.could_not_change_title_to({ title: updatableTitle }));
      console.error(e);
      return false;
    }
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

<Dialog.Root bind:open={showEditDialog}>
  <Dialog.Content class={dialogLayout.content()} closeLabel={m.close()}>
    <Dialog.Header class={dialogLayout.header}>
      <Dialog.Title>{m.edit_file()}</Dialog.Title>
      <Dialog.Description class="sr-only">{m.enter_new_file_name()}</Dialog.Description>
    </Dialog.Header>

    <div class={dialogLayout.body}>
      <div class={dialogLayout.section}>
        <Field.Field class="border-default hover:bg-hover-dimmer px-4 py-4">
          <Field.Label for={titleId}>{m.name()}</Field.Label>
          <Input id={titleId} bind:value={updatableTitle} />
        </Field.Field>
      </div>
    </div>
    <Dialog.Footer class={dialogLayout.footer}>
      <Dialog.Close class={buttonVariants({ variant: "outline" })}>{m.cancel()}</Dialog.Close>
      <Dialog.Close class={buttonVariants()} onclick={updateBlobName}
        >{m.save_changes()}</Dialog.Close
      >
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<ConfirmDialog
  bind:open={showDeleteDialog}
  title={m.delete_file()}
  description={m.confirm_delete_file({ fileName: blob.metadata.title || "" })}
  confirmLabel={m.delete()}
  errorContext={m.could_not_delete_file({ fileName: blob.metadata.title ?? m.this_file() })}
  onConfirm={deleteBlob}
/>
