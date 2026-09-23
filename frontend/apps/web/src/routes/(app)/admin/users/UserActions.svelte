<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { User } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import { MoreVertical, Edit, UserMinus, UserPlus, Trash2 } from "@lucide/svelte";
  import { invalidate } from "$app/navigation";
  import UserEditor from "./editor/UserEditor.svelte";
  import { getAppContext } from "$lib/core/AppContext";
  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";

  const eneo = getEneo();

  // Svelte 5 runes mode: use $props() instead of export let
  let { user } = $props<{ user: User }>();

  async function deleteUser() {
    isProcessing = true;
    try {
      await eneo.users.delete(user);
      invalidate("admin:users"); // Stable dependency key
      showDeleteDialog = false;
    } catch (e) {
      console.error(e);
    }
    isProcessing = false;
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

  let isProcessing = $state(false);
  let showEditDialog = $state(false);
  let showDeleteDialog = $state(false);
</script>

<DropdownMenu.Root>
  <DropdownMenu.Trigger>
    {#snippet child({ props })}
      <Button {...props} variant="ghost" size="icon" aria-label={m.actions()}>
        <MoreVertical size={16} />
      </Button>
    {/snippet}
  </DropdownMenu.Trigger>

  <DropdownMenu.Content align="end">
    <!-- Edit action - always available -->
    <DropdownMenu.Item
      onSelect={() => {
        showEditDialog = true;
      }}
    >
      <Edit size={16} />
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

<!-- Edit Dialog - hide built-in trigger since we control it from dropdown -->
<UserEditor {user} mode="update" hideTrigger={true} bind:open={showEditDialog}></UserEditor>

<!-- Delete Confirmation Dialog -->
<AlertDialog.Root bind:open={showDeleteDialog}>
  <AlertDialog.Content class={dialogLayout.content("small")}>
    <AlertDialog.Header class={dialogLayout.header}>
      <AlertDialog.Title>{m.delete_user()}</AlertDialog.Title>
      <AlertDialog.Description>
        {m.do_you_really_want_to_delete()}
        <span class="italic">{user.email}</span>?
      </AlertDialog.Description>
    </AlertDialog.Header>

    <AlertDialog.Footer class={dialogLayout.footer}>
      <AlertDialog.Cancel>{m.cancel()}</AlertDialog.Cancel>
      <Button variant="destructive" onclick={deleteUser}>
        {isProcessing ? m.deleting() : m.delete()}
      </Button>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
