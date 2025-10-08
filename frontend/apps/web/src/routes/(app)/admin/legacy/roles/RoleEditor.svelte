<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { invalidate } from "$app/navigation";
  import { makeEditable } from "$lib/core/editable";
  import { getIntric } from "$lib/core/Intric";
  import type { Permission, Role } from "@intric/intric-js";
  import { Dialog, Button, Input } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  const intric = getIntric();

  const emptyRole: Role = {
    id: "",
    name: "",
    permissions: []
  };

  export let mode: "update" | "create" = "create";
  export let role: Role = emptyRole;
  export let permissions: Array<{ name: Permission; description: string }>;
  export let disabled = false;

  let showDialog: Dialog.OpenState;
  let isProcessing = false;

  const editableRole = makeEditable(role ?? emptyRole);

  // Instead of deleting and re-creating this component, sveltekit will update the role variable
  // We update this component's view based on the role's value
  async function watchChanges(role: Role) {
    if (role !== editableRole.getOriginal()) {
      editableRole.updateWithValue(role);
    }
  }
  $: watchChanges(role);

  async function edit() {
    isProcessing = true;
    try {
      const role = { id: editableRole.id };
      await intric.roles.update({
        role,
        update: {
          ...editableRole.getEdits()
        }
      });
      invalidate("admin:roles:load");
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
      await intric.roles.create(editableRole);
      invalidate("admin:roles:load");
      $showDialog = false;
      editableRole.updateWithValue(emptyRole);
    } catch (error) {
      alert(error);
      console.error(error);
    }
    isProcessing = false;
  }

  function togglePermission(permission: Permission) {
    const index = editableRole.permissions.findIndex((current) => current === permission);
    if (index < 0) {
      editableRole.permissions = [...editableRole.permissions, permission];
      return;
    }
    editableRole.permissions = editableRole.permissions.toSpliced(index, 1);
  }
</script>

<Dialog.Root bind:isOpen={showDialog}>
  {#if mode === "create"}
    <Dialog.Trigger asFragment let:trigger>
      <Button variant="primary" is={trigger}>{m.create_role()}</Button>
    </Dialog.Trigger>
  {:else}
    <Dialog.Trigger asFragment let:trigger>
      <Button is={trigger}>{disabled ? m.view() : m.edit()}</Button>
    </Dialog.Trigger>
  {/if}

  <Dialog.Content width="medium" form>
    {#if mode === "create"}
      <Dialog.Title>{m.create_a_new_role()}</Dialog.Title>
    {:else}
      <Dialog.Title>{m.edit_role()}</Dialog.Title>
    {/if}

    <Dialog.Section>
      <Input.Text
        bind:value={editableRole.name}
        label={m.role_name()}
        description={m.descriptive_name_for_this_role()}
        required
        {disabled}
        class="border-default hover:bg-hover-stronger border-b px-4 py-4"
      ></Input.Text>
      <div class="px-4 py-4">
        <div class="flex items-baseline justify-between pb-2 pl-3 font-medium">
          {m.included_permissions()}<span class="text-secondary px-2 text-[0.9rem] font-normal"
            >{m.what_users_of_this_role_can_manage()}</span
          >
        </div>
        <div class="border-stronger bg-primary overflow-clip rounded-md border">
          {#each permissions as permission (permission)}
            <div
              class="border-default hover:bg-hover-dimmer flex flex-col gap-1 border-b px-4 py-4 last-of-type:border-b-0"
            >
              <Input.Switch
                {disabled}
                class="capitalize"
                value={editableRole.permissions.includes(permission.name)}
                sideEffect={() => {
                  togglePermission(permission.name);
                }}>{permission.name}</Input.Switch
              >
              <p class="text-secondary text-[0.9rem]">{permission.description}</p>
            </div>
          {/each}
        </div>
      </div>
    </Dialog.Section>

    <Dialog.Controls let:close>
      {#if !disabled}
        <Button is={close}>{m.cancel()}</Button>
        {#if mode === "create"}
          <Button variant="primary" on:click={create} type="submit" disabled={isProcessing}
            >{isProcessing ? m.creating() : m.create_role()}</Button
          >
        {:else}
          <Button variant="primary" on:click={edit} disabled={isProcessing}
            >{isProcessing ? m.saving() : m.save_changes()}</Button
          >
        {/if}
      {:else}
        <Button is={close} variant="outlined">{m.done()}</Button>
      {/if}
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
