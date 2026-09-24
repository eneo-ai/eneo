<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { User } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import { EllipsisVertical, SquarePen, UserMinus, UserPlus, Trash2 } from "@lucide/svelte";
  import { invalidate } from "$app/navigation";
  import UserEditor from "./editor/UserEditor.svelte";
  import { getAppContext } from "$lib/core/AppContext";
  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";

  const eneo = getEneo();

  // Svelte 5 runes mode: use $props() instead of export let
  let { user } = $props<{ user: User }>();

  async function deleteUser() {
    await eneo.users.delete(user);
    invalidate("admin:users"); // Stable dependency key
  }

  async function deactivateUser() {
    try {
      await eneo.users.deactivate({ user: { username: user.username } });
      invalidate("admin:users"); // Stable dependency key
    } catch (e) {
      console.error(e);
    }
  }

  async function reactivateUser() {
    try {
      await eneo.users.reactivate({ user: { username: user.username } });
      invalidate("admin:users"); // Stable dependency key
    } catch (e) {
      console.error(e);
    }
  }

  const { user: currentUser } = getAppContext();

  // Determine button visibility based on user state
  const isActive = $derived(user.state === "active" || user.state === "invited");
  const isInactive = $derived(user.state === "inactive");

  let showEditDialog = $state(false);
  let showDeleteDialog = $state(false);
</script>

<DropdownMenu.Root>
  <DropdownMenu.Trigger>
    {#snippet child({ props })}
      <Button {...props} variant="ghost" size="icon" aria-label={m.actions()}>
        <EllipsisVertical size={16} />
      </Button>
    {/snippet}
  </DropdownMenu.Trigger>

  <DropdownMenu.Content align="end">
    <!-- SquarePen action - always available -->
    <DropdownMenu.Item
      onSelect={() => {
        showEditDialog = true;
      }}
    >
      <SquarePen size={16} />
      {m.edit_user()}
    </DropdownMenu.Item>

    <!-- Deactivate - only for active/invited users -->
    {#if isActive}
      <DropdownMenu.Item disabled={user.id === currentUser.id} onSelect={deactivateUser}>
        <UserMinus size={16} />
        {m.deactivate_user()}
      </DropdownMenu.Item>
    {/if}

    <!-- Reactivate - only for inactive users -->
    {#if isInactive}
      <DropdownMenu.Item onSelect={reactivateUser}>
        <UserPlus size={16} />
        {m.reactivate_user()}
      </DropdownMenu.Item>
    {/if}

    <!-- Delete - always available but destructive -->
    <DropdownMenu.Item
      variant="destructive"
      disabled={user.id === currentUser.id}
      onSelect={() => {
        showDeleteDialog = true;
      }}
    >
      <Trash2 size={16} />
      {m.delete_user()}
    </DropdownMenu.Item>
  </DropdownMenu.Content>
</DropdownMenu.Root>

<!-- SquarePen Dialog - hide built-in trigger since we control it from dropdown -->
<UserEditor {user} mode="update" hideTrigger={true} bind:open={showEditDialog}></UserEditor>

<!-- Delete Confirmation Dialog -->
<ConfirmDialog
  bind:open={showDeleteDialog}
  title={m.delete_user()}
  confirmLabel={m.delete()}
  pendingLabel={m.deleting()}
  errorContext={m.could_not_delete_user()}
  onConfirm={deleteUser}
>
  {#snippet description()}
    {m.do_you_really_want_to_delete()}
    <span class="italic">{user.email}</span>?
  {/snippet}
</ConfirmDialog>
