<script lang="ts">
  import { IconTrash } from "@intric/icons/trash";
  import { Button, Dialog, Dropdown, Input } from "@intric/ui";
  import { invalidate } from "$app/navigation";
  import { getIntric } from "$lib/core/Intric";
  import type { InfoBlob } from "@intric/intric-js";
  import { IconEllipsis } from "@intric/icons/ellipsis";
  import { IconEdit } from "@intric/icons/edit";
  import { m } from "$lib/paraglide/messages";

  const intric = getIntric();
  export let blob: InfoBlob;
  export let canEdit: boolean;

  let updatableTitle = blob.metadata.title ?? "";
  async function updateBlobName() {
    try {
      await intric.infoBlobs.update({
        blob: { id: blob.id },
        update: { metadata: { title: updatableTitle } }
      });
      invalidate("blobs:list");
      return true;
    } catch (e) {
      alert(m.could_not_change_title_to({ title: updatableTitle }));
      console.error(e);
      return false;
    }
  }

  async function deleteBlob() {
    try {
      await intric.infoBlobs.delete(blob);
      invalidate("blobs:list");
      return true;
    } catch (e) {
      alert(m.could_not_delete_file({ fileName: blob.metadata.title ?? m.this_file() }));
      console.error(e);
      return false;
    }
  }

  let showDeleteDialog: Dialog.OpenState;
  let showEditDialog: Dialog.OpenState;
</script>

{#if canEdit}
  <Dropdown.Root>
    <Dropdown.Trigger asFragment let:trigger>
      <Button is={trigger} padding="icon">
        <IconEllipsis />
      </Button>
    </Dropdown.Trigger>

    <Dropdown.Menu let:item>
      <Button
        is={item}
        on:click={() => {
          $showEditDialog = true;
        }}
        padding="icon-leading"
      >
        <IconEdit size="sm" />
        {m.edit()}</Button
      >
      <Button
        is={item}
        variant="destructive"
        on:click={() => {
          $showDeleteDialog = true;
        }}
        padding="icon-leading"
      >
        <IconTrash size="sm" />{m.delete()}</Button
      >
    </Dropdown.Menu>
  </Dropdown.Root>
{/if}

<Dialog.Root bind:isOpen={showEditDialog}>
  <Dialog.Content width="small">
    <Dialog.Title>{m.edit_file()}</Dialog.Title>
    <Dialog.Description hidden>{m.enter_new_file_name()}</Dialog.Description>

    <Dialog.Section>
      <Input.Text
        bind:value={updatableTitle}
        label={m.name()}
        class=" border-default hover:bg-hover-dimmer px-4 py-4"
      ></Input.Text>
    </Dialog.Section>
    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button is={close} variant="primary" on:click={updateBlobName}>{m.save_changes()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root alert bind:isOpen={showDeleteDialog}>
  <Dialog.Content width="small">
    <Dialog.Title>{m.delete_group()}</Dialog.Title>
    <Dialog.Description
      >{m.confirm_delete_file({ fileName: blob.metadata.title || "" })}</Dialog.Description
    >

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button is={close} variant="destructive" on:click={deleteBlob}>{m.delete()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
