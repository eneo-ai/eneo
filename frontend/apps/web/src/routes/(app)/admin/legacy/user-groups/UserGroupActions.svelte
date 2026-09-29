<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconTrash } from "@eneo/icons/trash";
  import { Button } from "$lib/components/ui/button/index.js";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import type { UserGroup } from "@eneo/eneo-js";
  import UserGroupEditor from "./UserGroupEditor.svelte";
  import UserGroupMembersEditor from "./UserGroupMembersEditor.svelte";
  import { getEneo } from "$lib/core/Eneo";
  import { invalidate } from "$app/navigation";
  import { m } from "$lib/paraglide/messages";

  export let userGroup: UserGroup;

  const eneo = getEneo();

  async function deleteResource() {
    await eneo.userGroups.delete(userGroup);
    invalidate("admin:user-groups:load");
  }
</script>

<UserGroupMembersEditor {userGroup}></UserGroupMembersEditor>

<div class="w-2"></div>

<UserGroupEditor {userGroup} mode="update"></UserGroupEditor>

<div class="w-2"></div>

<ConfirmDialog
  title={m.delete_user_group()}
  confirmLabel={m.delete()}
  pendingLabel={m.deleting()}
  errorContext={m.could_not_delete_user_group()}
  onConfirm={deleteResource}
>
  {#snippet trigger({ props })}
    <Button {...props} variant="destructive" size="icon" aria-label={m.delete_user_group()}>
      <IconTrash />
    </Button>
  {/snippet}
  {#snippet description()}
    {m.do_you_really_want_to_delete()}
    <span class="italic">{userGroup.name}</span>?
  {/snippet}
</ConfirmDialog>
