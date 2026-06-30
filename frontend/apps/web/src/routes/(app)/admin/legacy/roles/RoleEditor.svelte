<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { invalidate } from "$app/navigation";
  import { makeEditable } from "$lib/core/editable";
  import { getEneo } from "$lib/core/Eneo";
  import type { Permission, Role } from "@eneo/eneo-js";
  import { Dialog, Button, Input } from "@eneo/ui";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";
  import { getPermissionCopy } from "./permission-labels";

  const eneo = getEneo();

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
  // Input.Text does not expose its inner <input>, so we wrap it in a ref'd
  // container and query the input on open. Needed to autofocus the name.
  let nameFieldContainer: HTMLDivElement | null = null;

  const editableRole = makeEditable(role ?? emptyRole);

  $: hasTemplate = "predefined_source" in role && role.predefined_source;
  $: selectedCount = editableRole.permissions.length;
  $: totalPermissions = permissions.length;
  // Dirty check: has the user actually changed something worth saving?
  // Compares trimmed name and sorted permission arrays so reordering isn't
  // treated as a change and whitespace-only edits don't enable the button.
  $: isDirty = (() => {
    const nameChanged = (editableRole.name ?? "").trim() !== (role?.name ?? "").trim();
    const origPerms = [...(role?.permissions ?? [])].sort();
    const editedPerms = [...editableRole.permissions].sort();
    const permsChanged =
      origPerms.length !== editedPerms.length || origPerms.some((p, i) => p !== editedPerms[i]);
    return nameChanged || permsChanged;
  })();
  $: canSubmit =
    !isProcessing && editableRole.name.trim().length > 0 && (mode === "create" || isDirty);

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
      await eneo.roles.update({
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
      await eneo.roles.create(editableRole);
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
      await eneo.roles.resetToDefault(role);
      invalidate("admin:roles:load");
    } catch (error) {
      toastError(error);
    }
    isProcessing = false;
  }

  async function setAsDefault() {
    isProcessing = true;
    try {
      await eneo.roles.setAsDefault(role);
      invalidate("admin:roles:load");
      window.location.reload();
    } catch (error) {
      toastError(error);
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

  // Autofocus the name input when the create dialog opens. Edit mode skips
  // this — focusing a pre-filled input mid-session is jarring and selects
  // nothing useful.
  $: if ($showDialog && mode === "create" && nameFieldContainer) {
    // Defer a tick so the Dialog's own focus trap doesn't fight us.
    queueMicrotask(() => {
      const input = nameFieldContainer?.querySelector("input");
      input?.focus();
    });
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
          <div class="pb-2 pl-3 font-medium">{m.start_from_template()}</div>
          <div class="flex flex-wrap gap-2 pl-3" role="group" aria-label={m.start_from_template()}>
            {#each templates as template (template.name)}
              <Button variant="outlined" on:click={() => applyTemplate(template)}>
                {template.name}
              </Button>
            {/each}
          </div>
        </div>
      {/if}
      <div bind:this={nameFieldContainer}>
        <Input.Text
          bind:value={editableRole.name}
          label={m.role_name()}
          description={m.descriptive_name_for_this_role()}
          required
          class="border-default hover:bg-hover-stronger border-b px-4 py-4"
        ></Input.Text>
      </div>
      <div class="px-4 py-4">
        <div
          class="flex flex-col gap-1 pb-2 pl-3 sm:flex-row sm:flex-wrap sm:items-baseline sm:justify-between sm:gap-2"
        >
          <span class="flex items-baseline gap-2 font-medium">
            {m.included_permissions()}
            <span
              class="bg-secondary text-secondary rounded-full px-2 py-0.5 text-[0.75rem] font-medium tabular-nums"
              aria-live="polite"
            >
              {m.permissions_selected_count({ selected: selectedCount, total: totalPermissions })}
            </span>
          </span>
          <span class="text-secondary text-[0.9rem] font-normal sm:px-2">
            {m.what_users_of_this_role_can_manage()}
          </span>
        </div>
        <div class="border-stronger bg-primary overflow-clip rounded-md border">
          {#each permissions as permission (permission)}
            {@const copy = getPermissionCopy(permission.name, permission.description)}
            <div
              class="border-default hover:bg-hover-dimmer flex flex-col gap-1 border-b px-4 py-4 last-of-type:border-b-0"
            >
              <Input.Switch
                value={editableRole.permissions.includes(permission.name)}
                sideEffect={() => {
                  togglePermission(permission.name);
                }}>{copy.label}</Input.Switch
              >
              <p class="text-secondary text-[0.9rem]">{copy.description}</p>
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
              {m.reset_to_template()}
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
              {m.set_as_default()}
            </Button>
          {/if}
        </div>
      {/if}

      <Button is={close}>{m.cancel()}</Button>
      {#if mode === "create"}
        <Button variant="primary" on:click={create} type="submit" disabled={!canSubmit}
          >{isProcessing ? m.creating() : m.create_role()}</Button
        >
      {:else}
        <Button variant="primary" on:click={edit} disabled={!canSubmit}
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
      <Dialog.Title>{m.reset_to_template()}</Dialog.Title>
      <Dialog.Description>
        {m.reset_to_template_description({ name: role.name })}
      </Dialog.Description>
      <Dialog.Controls let:close>
        <Button is={close}>{m.cancel()}</Button>
        <Button is={close} variant="primary" on:click={resetToTemplate}>{m.reset()}</Button>
      </Dialog.Controls>
    </Dialog.Content>
  </Dialog.Root>
{/if}

<!-- Set as default confirmation -->
{#if mode === "update" && !isDefault}
  <Dialog.Root bind:isOpen={showDefaultConfirm} alert>
    <Dialog.Content width="small">
      <Dialog.Title>{m.set_as_default_role()}</Dialog.Title>
      <Dialog.Description>
        {m.set_as_default_role_description({ name: role.name })}
      </Dialog.Description>
      <Dialog.Controls let:close>
        <Button is={close}>{m.cancel()}</Button>
        <Button is={close} variant="primary" on:click={setAsDefault}>{m.confirm()}</Button>
      </Dialog.Controls>
    </Dialog.Content>
  </Dialog.Root>
{/if}
