<script lang="ts">
  import { type IntegrationKnowledge } from "@intric/intric-js";
  import { IconEllipsis } from "@intric/icons/ellipsis";
  import { IconTrash } from "@intric/icons/trash";
  import { IconEdit } from "@intric/icons/edit";
  import { Button, Dialog, Dropdown, Input } from "@intric/ui";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";

  export let knowledgeItem: IntegrationKnowledge;

  const intric = getIntric();
  const {
    refreshCurrentSpace,
    state: { currentSpace }
  } = getSpacesManager();

  let isDeleting = false;
  let isRenaming = false;
  let newName = knowledgeItem.name;

  async function deleteKnowledge() {
    isDeleting = true;
    try {
      await intric.integrations.knowledge.delete({
        knowledge: knowledgeItem,
        space: $currentSpace
      });
      refreshCurrentSpace();
      $showDeleteDialog = false;
    } catch (e) {
      alert(m.could_not_delete_crawl());
      console.error(e);
    }
    isDeleting = false;
  }

  async function renameKnowledge() {
    isRenaming = true;
    try {
      await intric.integrations.knowledge.rename({
        knowledge: knowledgeItem,
        space: $currentSpace,
        name: newName
      });
      refreshCurrentSpace();
      $showRenameDialog = false;
    } catch (e) {
      alert(m.integration_rename_error());
      console.error(e);
    }
    isRenaming = false;
  }

  let showDeleteDialog: Dialog.OpenState;
  let showRenameDialog: Dialog.OpenState;
</script>

<Dropdown.Root>
  <Dropdown.Trigger let:trigger asFragment>
    <Button is={trigger} padding="icon">
      <IconEllipsis />
    </Button>
  </Dropdown.Trigger>
  <Dropdown.Menu let:item>
    {#if knowledgeItem.permissions?.includes("edit")}
      <Button
        is={item}
        on:click={() => {
          newName = knowledgeItem.name;
          $showRenameDialog = true;
        }}
        padding="icon-leading"
      >
        <IconEdit size="sm" />{m.rename()}</Button
      >
    {/if}
    {#if knowledgeItem.permissions?.includes("delete")}
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
    {/if}
  </Dropdown.Menu>
</Dropdown.Root>

<Dialog.Root bind:isOpen={showRenameDialog}>
  <Dialog.Content width="small">
    <Dialog.Title>{m.integration_rename_title()}</Dialog.Title>
    <Dialog.Section scrollable={false}>
      <Input.Text bind:value={newName} label={m.name()} class="px-4 py-4" />
    </Dialog.Section>
    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="primary" on:click={renameKnowledge} disabled={!newName.trim()}
        >{isRenaming ? m.saving() : m.save()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root alert bind:isOpen={showDeleteDialog}>
  <Dialog.Content width="small">
    <Dialog.Title>{m.delete_integration_knowledge()}</Dialog.Title>
    <Dialog.Description>
      {m.confirm_delete_integration_knowledge({ knowledgeName: knowledgeItem.name })}
    </Dialog.Description>
    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="destructive" on:click={deleteKnowledge}
        >{isDeleting ? m.deleting() : m.delete()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
