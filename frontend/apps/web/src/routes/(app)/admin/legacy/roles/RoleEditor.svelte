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
  import { toastError } from "$lib/core/errors";

  const intric = getIntric();

  const emptyRole: Role = {
    id: "",
    name: "",
    permissions: []
  };

  export let mode: "update" | "create" = "create";
  export let role: Role = emptyRole;
  export let permissions: Array<{ name: Permission; description: string }>;
  export let isDefault = false;
  export let templates: Array<{ name: string; permissions: string[] }> = [];

  let showDialog: Dialog.OpenState;
  let showResetConfirm: Dialog.OpenState;
  let showDefaultConfirm: Dialog.OpenState;
  let isProcessing = false;

  const editableRole = makeEditable(role ?? emptyRole);

  $: hasTemplate = "predefined_source" in role && role.predefined_source;

  function applyTemplate(template: { name: string; permissions: string[] }) {
    editableRole.name = template.name;
    editableRole.permissions = [...template.permissions] as Permission[];
  }

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
      toastError(error);
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
      toastError(error);
      console.error(error);
    }
    isProcessing = false;
  }

  async function resetToTemplate() {
    isProcessing = true;
    try {
      await intric.roles.resetToDefault(role);
      invalidate("admin:roles:load");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    }
    isProcessing = false;
  }

  async function setAsDefault() {
    isProcessing = true;
    try {
      await intric.roles.setAsDefault(role);
      invalidate("admin:roles:load");
      window.location.reload();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
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

<!-- Main edit/create dialog -->
<Dialog.Root bind:isOpen={showDialog}>
  {#if mode === "create"}
    <Dialog.Trigger asFragment let:trigger>
      <Button variant="primary" is={trigger}>{m.create_role()}</Button>
    </Dialog.Trigger>
  {:else}
    <Dialog.Trigger asFragment let:trigger>
      <Button is={trigger}>{m.edit()}</Button>
    </Dialog.Trigger>
  {/if}

  <Dialog.Content width="medium" form>
    {#if mode === "create"}
      <Dialog.Title>{m.create_a_new_role()}</Dialog.Title>
    {:else}
      <Dialog.Title>{m.edit_role()}</Dialog.Title>
    {/if}

    <Dialog.Section>
      {#if mode === "create" && templates.length > 0}
        <div class="border-default border-b px-4 py-4">
          <div class="pb-2 pl-3 font-medium">Start from template</div>
          <div class="flex flex-wrap gap-2 pl-3">
            {#each templates as template (template.name)}
              <Button variant="outlined" on:click={() => applyTemplate(template)}
                >{template.name}</Button
              >
            {/each}
          </div>
        </div>
      {/if}
      <Input.Text
        bind:value={editableRole.name}
        label={m.role_name()}
        description={m.descriptive_name_for_this_role()}
        required
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
      {#if mode === "update"}
        <div class="flex flex-1 gap-2">
          {#if hasTemplate}
            <Button
              variant="outlined"
              disabled={isProcessing}
              on:click={() => {
                $showDialog = false;
                $showResetConfirm = true;
              }}
            >
              Reset to template
            </Button>
          {/if}
          {#if !isDefault}
            <Button
              variant="outlined"
              disabled={isProcessing}
              on:click={() => {
                $showDialog = false;
                $showDefaultConfirm = true;
              }}
            >
              Set as default
            </Button>
          {/if}
        </div>
      {/if}

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
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<!-- Reset to template confirmation -->
{#if mode === "update" && hasTemplate}
  <Dialog.Root bind:isOpen={showResetConfirm} alert>
    <Dialog.Content width="small">
      <Dialog.Title>Reset to template</Dialog.Title>
      <Dialog.Description>
        Are you sure you want to reset <span class="italic">{role.name}</span> to its original template?
        Both the name and permissions will be restored to their defaults.
      </Dialog.Description>
      <Dialog.Controls let:close>
        <Button is={close}>{m.cancel()}</Button>
        <Button is={close} variant="primary" on:click={resetToTemplate}>Reset</Button>
      </Dialog.Controls>
    </Dialog.Content>
  </Dialog.Root>
{/if}

<!-- Set as default confirmation -->
{#if mode === "update" && !isDefault}
  <Dialog.Root bind:isOpen={showDefaultConfirm} alert>
    <Dialog.Content width="small">
      <Dialog.Title>Set as default role</Dialog.Title>
      <Dialog.Description>
        Are you sure you want to set <span class="italic">{role.name}</span> as the default role? New
        users will automatically be assigned this role.
      </Dialog.Description>
      <Dialog.Controls let:close>
        <Button is={close}>{m.cancel()}</Button>
        <Button is={close} variant="primary" on:click={setAsDefault}>Confirm</Button>
      </Dialog.Controls>
    </Dialog.Content>
  </Dialog.Root>
{/if}
