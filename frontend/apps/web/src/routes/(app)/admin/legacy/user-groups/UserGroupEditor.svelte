<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { invalidate } from "$app/navigation";
  import { makeEditable } from "$lib/core/editable";
  import { getIntric } from "$lib/core/Intric";
  import type { UserGroup } from "@intric/intric-js";
  import { Dialog, Button, Input } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  const emptyUserGroup: UserGroup = {
    id: "",
    name: ""
  };

  const intric = getIntric();

  export let mode: "update" | "create" = "create";
  export let userGroup: UserGroup = emptyUserGroup;

  let showDialog: Dialog.OpenState;
  let isProcessing = false;

  const editableUserGroup = makeEditable(userGroup ?? emptyUserGroup);

  // Instead of deleting and re-creating this component, sveltekit will update the userGroup variable
  // We update this component's view based on the userGroup's value
  async function watchChanges(userGroup: UserGroup) {
    if (userGroup !== editableUserGroup.getOriginal()) {
      editableUserGroup.updateWithValue(userGroup);
    }
  }

  $: watchChanges(userGroup);

  async function edit() {
    isProcessing = true;
    try {
      const updated = await intric.userGroups.update({
        userGroup: { id: userGroup.id },
        update: editableUserGroup.getEdits()
      });
      editableUserGroup.updateWithValue(updated);
      invalidate("admin:user-groups:load");
      $showDialog = false;
    } catch (error) {
      alert(error);
      console.error(error);
    }
    isProcessing = false;
  }

  async function create() {
    isProcessing = true;
    try {
      await intric.userGroups.create(editableUserGroup);
      invalidate("admin:user-groups:load");
      $showDialog = false;
      editableUserGroup.updateWithValue(emptyUserGroup);
    } catch (error) {
      alert(error);
      console.error(error);
    }
    isProcessing = false;
  }
</script>

<Dialog.Root bind:isOpen={showDialog}>
  {#if mode === "create"}
    <Dialog.Trigger asFragment let:trigger>
      <Button variant="primary" is={trigger}>{m.create_user_group()}</Button>
    </Dialog.Trigger>
  {:else}
    <Dialog.Trigger asFragment let:trigger>
      <Button is={trigger}>{m.edit()}</Button>
    </Dialog.Trigger>
  {/if}

  <Dialog.Content width="medium" form>
    {#if mode === "create"}
      <Dialog.Title>{m.create_new_user_group()}</Dialog.Title>
    {:else}
      <Dialog.Title>{m.edit_user_group()}</Dialog.Title>
    {/if}

    <Dialog.Section>
      <div class="hover:bg-hover-dimmer">
        <Input.Text
          bind:value={editableUserGroup.name}
          label={m.group_name()}
          descripton={m.descriptive_name_for_group()}
          required
          class="border-default px-4 py-4  {mode === 'create' ? 'border-b' : ''}"
        ></Input.Text>
      </div>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      {#if mode === "create"}
        <Button variant="primary" on:click={create} type="submit" disabled={isProcessing}
          >{isProcessing ? m.creating() : m.create_user_group()}</Button
        >
      {:else}
        <Button variant="primary" on:click={edit} disabled={isProcessing}
          >{isProcessing ? m.saving() : m.save_changes()}</Button
        >
      {/if}
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
