<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconTrash } from "@intric/icons/trash";
  import { Button, Dialog } from "@intric/ui";
  import { invalidate } from "$app/navigation";
  import type { User } from "@intric/intric-js";
  import UserEditor from "./editor/UserEditor.svelte";
  import { getAppContext } from "$lib/core/AppContext";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";

  const intric = getIntric();
  export let user: User;

  async function deleteUser() {
    try {
      await intric.users.delete(user);
      invalidate("admin:users:load");
    } catch (e) {
      console.error(e);
    }
  }

  const { user: currentUser } = getAppContext();
</script>

<UserEditor {user} mode="update"></UserEditor>

<div class="w-2"></div>

<Dialog.Root alert>
  <Dialog.Trigger asFragment let:trigger>
    <Button
      is={trigger}
      label={m.delete_user()}
      variant="destructive"
      padding="icon"
      disabled={user.username === currentUser.username}
    >
      <IconTrash />
    </Button>
  </Dialog.Trigger>

  <Dialog.Content width="small">
    <Dialog.Title>{m.delete_user()}</Dialog.Title>
    <Dialog.Description
      >{m.do_you_really_want_to_delete()} <span class="italic">{user.username}</span>?</Dialog.Description
    >

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button is={close} variant="destructive" on:click={deleteUser}>{m.delete()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
