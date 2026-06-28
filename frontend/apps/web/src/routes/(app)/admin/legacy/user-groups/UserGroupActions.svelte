<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconTrash } from "@eneo/icons/trash";
  import { Button, Dialog } from "@eneo/ui";
  import type { UserGroup } from "@eneo/eneo-js";
  import UserGroupEditor from "./UserGroupEditor.svelte";
  import UserGroupMembersEditor from "./UserGroupMembersEditor.svelte";
  import { getEneo } from "$lib/core/Eneo";
  import { invalidate } from "$app/navigation";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";

  export let userGroup: UserGroup;

  const eneo = getEneo();

  let isDeleting = false;
  let showDeleteDialog: Dialog.OpenState;
  async function deleteResource() {
    isDeleting = true;
    try {
      await eneo.userGroups.delete(userGroup);
      invalidate("admin:user-groups:load");
      $showDeleteDialog = false;
    } catch (e) {
      toastError(e, m.could_not_delete_user_group());
      console.error(e);
    }
    isDeleting = false;
  }
</script>

<UserGroupMembersEditor {userGroup}></UserGroupMembersEditor>

<div class="w-2"></div>

<UserGroupEditor {userGroup} mode="update"></UserGroupEditor>

<div class="w-2"></div>

<Dialog.Root alert bind:isOpen={showDeleteDialog}>
  <Dialog.Trigger asFragment let:trigger>
    <Button is={trigger} label={m.delete_user_group()} variant="destructive" padding="icon">
      <IconTrash />
    </Button>
  </Dialog.Trigger>

  <Dialog.Content width="small">
    <Dialog.Title>{m.delete_user_group()}</Dialog.Title>
    <Dialog.Description
      >{m.do_you_really_want_to_delete()}
      <span class="italic">{userGroup.name}</span>?</Dialog.Description
    >

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button disabled={isDeleting} variant="destructive" on:click={deleteResource}
        >{isDeleting ? m.deleting() : m.delete()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
