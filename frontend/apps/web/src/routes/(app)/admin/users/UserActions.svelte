<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { User } from "@intric/intric-js";
  import { Button, Dialog, Dropdown } from "@intric/ui";
  import { MoreVertical, Edit, UserMinus, UserPlus, Trash2 } from "lucide-svelte";
  import { invalidate } from "$app/navigation";
  import UserEditor from "./editor/UserEditor.svelte";
  import { getAppContext } from "$lib/core/AppContext";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";

  const intric = getIntric();

  // Svelte 5 runes mode: use $props() instead of export let
  let { user } = $props<{ user: User }>();

  async function deleteUser() {
    isProcessing = true;
    try {
      await intric.users.delete(user);
      invalidate("admin:users");  // Stable dependency key
      $showDeleteDialog = false;
    } catch (e) {
      console.error(e);
    }
    isProcessing = false;
  }

  async function deactivateUser() {
    try {
      await intric.users.deactivate({ user: { username: user.username } });
      invalidate("admin:users");  // Stable dependency key
    } catch (e) {
      console.error(e);
    }
  }

  async function reactivateUser() {
    try {
      await intric.users.reactivate({ user: { username: user.username } });
      invalidate("admin:users");  // Stable dependency key
    } catch (e) {
      console.error(e);
    }
  }

  const { user: currentUser } = getAppContext();

  // Determine button visibility based on user state
  const isActive = $derived(user.state === 'active' || user.state === 'invited');
  const isInactive = $derived(user.state === 'inactive');

  let isProcessing = false;
  let showEditDialog: Dialog.OpenState;
  let showDeleteDialog: Dialog.OpenState;
</script>

<Dropdown.Root>
  <Dropdown.Trigger asFragment let:trigger>
    <Button
      is={trigger}
      padding="icon"
      aria-label={m.actions()}
    >
      <MoreVertical size={16} />
    </Button>
  </Dropdown.Trigger>

  <Dropdown.Menu let:item>
    <!-- Edit action - always available -->
    <Button
      is={item}
      padding="icon-leading"
      on:click={() => {
        $showEditDialog = true;
      }}
    >
      <Edit size={16} />
      {m.edit_user()}
    </Button>

    <!-- Deactivate - only for active/invited users -->
    {#if isActive}
      <Button
        is={item}
        padding="icon-leading"
        disabled={user.id === currentUser.id}
        on:click={deactivateUser}
      >
        <UserMinus size={16} />
        {m.deactivate_user()}
      </Button>
    {/if}

    <!-- Reactivate - only for inactive users -->
    {#if isInactive}
      <Button
        is={item}
        padding="icon-leading"
        on:click={reactivateUser}
      >
        <UserPlus size={16} />
        {m.reactivate_user()}
      </Button>
    {/if}

    <!-- Delete - always available but destructive -->
    <Button
      is={item}
      variant="destructive"
      padding="icon-leading"
      disabled={user.id === currentUser.id}
      on:click={() => {
        $showDeleteDialog = true;
      }}
    >
      <Trash2 size={16} />
      {m.delete_user()}
    </Button>
  </Dropdown.Menu>
</Dropdown.Root>

<!-- Edit Dialog - hide built-in trigger since we control it from dropdown -->
<UserEditor {user} mode="update" hideTrigger={true} bind:showDialog={showEditDialog}></UserEditor>

<!-- Delete Confirmation Dialog -->
<Dialog.Root alert bind:isOpen={showDeleteDialog}>
  <Dialog.Content width="small">
    <Dialog.Title>{m.delete_user()}</Dialog.Title>
    <Dialog.Description>
      {m.do_you_really_want_to_delete()}
      <span class="italic">{user.email}</span>?
    </Dialog.Description>

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="destructive" on:click={deleteUser}>
        {isProcessing ? m.deleting() : m.delete()}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
