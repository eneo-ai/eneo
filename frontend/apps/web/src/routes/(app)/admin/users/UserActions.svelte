<script lang="ts">
  import { IconEdit } from "@intric/icons/edit";
  import { IconTrash } from "@intric/icons/trash";
  import { IconEllipsis } from "@intric/icons/ellipsis";
  import { IconLink } from "@intric/icons/link";
  import { Button, Dialog, Dropdown } from "@intric/ui";
  import type { User } from "@intric/intric-js";
  import { getIntric } from "$lib/core/Intric";
  import { getAppContext } from "$lib/core/AppContext";
  import { invalidate } from "$app/navigation";
  import InviteLinkDialog from "./editor/InviteLinkDialog.svelte";
  import UserEditor from "./editor/UserEditor.svelte";
  import { m } from "$lib/paraglide/messages";

  const intric = getIntric();
  export let user: User;

  const { user: currentUser } = getAppContext();

  let isProcessing = false;
  let showDeleteDialog: Dialog.OpenState;
  async function deleteUser() {
    isProcessing = true;
    try {
      await intric.users.delete(user);
      invalidate("admin:users:load");
      $showDeleteDialog = false;
    } catch (e) {
      alert(m.could_not_delete_user());
      console.error(e);
    }
    isProcessing = false;
  }

  let showInviteDialog: Dialog.OpenState;
  let showEditDialog: Dialog.OpenState;
</script>

<Dropdown.Root>
  <Dropdown.Trigger let:trigger asFragment>
    <Button is={trigger} disabled={false} padding="icon">
      <IconEllipsis></IconEllipsis>
    </Button>
  </Dropdown.Trigger>
  <Dropdown.Menu let:item>
    <Button
      is={item}
      padding="icon-leading"
      on:click={() => {
        $showEditDialog = true;
      }}
    >
      <IconEdit size="sm"></IconEdit>
      {m.edit()}</Button
    >

    {#if !user.is_active}
      <Button
        is={item}
        padding="icon-leading"
        on:click={() => {
          $showInviteDialog = true;
        }}
      >
        <IconLink size="sm" />
        {m.show_invite_link()}</Button
      >
    {/if}

    <Button
      is={item}
      variant="destructive"
      on:click={() => {
        $showDeleteDialog = true;
      }}
      disabled={currentUser.id === user.id}
      padding="icon-leading"
    >
      <IconTrash size="sm"></IconTrash>{m.delete()}</Button
    >
  </Dropdown.Menu>
</Dropdown.Root>

<Dialog.Root alert bind:isOpen={showDeleteDialog}>
  <Dialog.Content width="small">
    <Dialog.Title>{m.delete_user()}</Dialog.Title>
    <Dialog.Description
      >{m.do_you_really_want_to_delete()} <span class="italic">{user.email}</span>?</Dialog.Description
    >

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="destructive" on:click={deleteUser}
        >{isProcessing ? m.deleting() : m.delete()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<InviteLinkDialog bind:isOpen={showInviteDialog} {user}></InviteLinkDialog>

<UserEditor bind:isOpen={showEditDialog} {user}></UserEditor>
