<script lang="ts">
  import { type IntegrationKnowledge } from "@eneo/eneo-js";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { IconTrash } from "@eneo/icons/trash";
  import { IconEdit } from "@eneo/icons/edit";
  import { IconRefresh } from "@eneo/icons/refresh";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import { useId } from "bits-ui";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";

  export let knowledgeItem: IntegrationKnowledge;

  const eneo = getEneo();
  const {
    refreshCurrentSpace,
    state: { currentSpace }
  } = getSpacesManager();

  let isRenaming = false;
  let newName = knowledgeItem.name;
  const nameId = useId();

  async function deleteKnowledge() {
    await eneo.integrations.knowledge.delete({
      knowledge: knowledgeItem,
      space: $currentSpace
    });
    refreshCurrentSpace();
  }

  async function renameKnowledge() {
    isRenaming = true;
    try {
      await eneo.integrations.knowledge.rename({
        knowledge: knowledgeItem,
        space: $currentSpace,
        name: newName
      });
      refreshCurrentSpace();
      showRenameDialog = false;
    } catch (e) {
      toastError(e, m.integration_rename_error());
      console.error(e);
    }
    isRenaming = false;
  }

  async function triggerFullSync() {
    await eneo.integrations.knowledge.triggerFullSync({
      knowledge: knowledgeItem,
      space: $currentSpace
    });
    refreshCurrentSpace();
  }

  let showDeleteDialog = false;
  let showRenameDialog = false;
  let showSyncDialog = false;
</script>

<DropdownMenu.Root>
  <DropdownMenu.Trigger>
    {#snippet child({ props })}
      <Button {...props} variant="ghost" size="icon" aria-label={m.actions()}>
        <IconEllipsis />
      </Button>
    {/snippet}
  </DropdownMenu.Trigger>
  <DropdownMenu.Content align="end">
    {#if knowledgeItem.permissions?.includes("edit")}
      <DropdownMenu.Item
        onSelect={() => {
          newName = knowledgeItem.name;
          showRenameDialog = true;
        }}
      >
        <IconEdit size="sm" />{m.rename()}
      </DropdownMenu.Item>
    {/if}
    {#if knowledgeItem.integration_type === "sharepoint" && knowledgeItem.permissions?.includes("edit")}
      <DropdownMenu.Item onSelect={() => (showSyncDialog = true)}>
        <IconRefresh size="sm" />{m.trigger_full_sync()}
      </DropdownMenu.Item>
    {/if}
    {#if knowledgeItem.permissions?.includes("delete")}
      <DropdownMenu.Item variant="destructive" onSelect={() => (showDeleteDialog = true)}>
        <IconTrash size="sm" />{m.delete()}
      </DropdownMenu.Item>
    {/if}
  </DropdownMenu.Content>
</DropdownMenu.Root>

<Dialog.Root bind:open={showRenameDialog}>
  <Dialog.Content class={dialogLayout.content()} closeLabel={m.close()}>
    <Dialog.Header class={dialogLayout.header}>
      <Dialog.Title>{m.integration_rename_title()}</Dialog.Title>
    </Dialog.Header>
    <div class={dialogLayout.body}>
      <div class={dialogLayout.section}>
        <Field.Field class="px-4 py-4">
          <Field.Label for={nameId}>{m.name()}</Field.Label>
          <Input id={nameId} bind:value={newName} />
        </Field.Field>
      </div>
    </div>
    <Dialog.Footer class={dialogLayout.footer}>
      <Dialog.Close class={buttonVariants({ variant: "outline" })}>{m.cancel()}</Dialog.Close>
      <Button onclick={renameKnowledge} disabled={!newName.trim()}
        >{isRenaming ? m.saving() : m.save()}</Button
      >
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<ConfirmDialog
  bind:open={showSyncDialog}
  title={m.trigger_full_sync()}
  description={m.confirm_full_sync({ knowledgeName: knowledgeItem.name })}
  confirmLabel={m.start_full_sync()}
  pendingLabel={m.syncing()}
  variant="default"
  onConfirm={triggerFullSync}
/>

<ConfirmDialog
  bind:open={showDeleteDialog}
  title={m.delete_integration_knowledge()}
  description={m.confirm_delete_integration_knowledge({ knowledgeName: knowledgeItem.name })}
  confirmLabel={m.delete()}
  pendingLabel={m.deleting()}
  errorContext={m.integration_delete_error()}
  onConfirm={deleteKnowledge}
/>
