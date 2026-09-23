<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconTrash } from "@eneo/icons/trash";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
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
  let showDeleteDialog = false;
  async function deleteResource() {
    isDeleting = true;
    try {
      await eneo.userGroups.delete(userGroup);
      invalidate("admin:user-groups:load");
      showDeleteDialog = false;
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

<AlertDialog.Root bind:open={showDeleteDialog}>
  <AlertDialog.Trigger>
    {#snippet child({ props })}
      <Button {...props} variant="destructive" size="icon" aria-label={m.delete_user_group()}>
        <IconTrash />
      </Button>
    {/snippet}
  </AlertDialog.Trigger>

  <AlertDialog.Content class={dialogLayout.content("small")}>
    <AlertDialog.Header class={dialogLayout.header}>
      <AlertDialog.Title>{m.delete_user_group()}</AlertDialog.Title>
      <AlertDialog.Description
        >{m.do_you_really_want_to_delete()}
        <span class="italic">{userGroup.name}</span>?</AlertDialog.Description
      >
    </AlertDialog.Header>

    <AlertDialog.Footer class={dialogLayout.footer}>
      <AlertDialog.Cancel>{m.cancel()}</AlertDialog.Cancel>
      <Button disabled={isDeleting} variant="destructive" onclick={deleteResource}
        >{isDeleting ? m.deleting() : m.delete()}</Button
      >
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
