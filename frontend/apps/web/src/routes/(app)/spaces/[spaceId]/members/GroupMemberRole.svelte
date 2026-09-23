<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconTrash } from "@eneo/icons/trash";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import { getEneo } from "$lib/core/Eneo";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import type { Space, SpaceRole } from "@eneo/eneo-js";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";

  type GroupMember = Space["group_members"]["items"][number];
  type RoleOption = { label: string; value: SpaceRole["value"] };

  type Props = {
    groupMember: GroupMember;
  };

  let { groupMember }: Props = $props();
  const eneo = getEneo();

  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  const options: RoleOption[] = $currentSpace.available_roles;

  // After changing the role we update with the passed prop as source of truth
  let selectedRole = $derived(groupMember.role);

  const removeGroupMember = createAsyncState(async () => {
    try {
      await eneo.spaces.groupMembers.remove({ spaceId: $currentSpace.id, group: groupMember });
      showRemoveDialog = false;
      // Will cause an update in the parent page and remove this component instance from the tree
      refreshCurrentSpace();
    } catch (e) {
      toastError(e, m.couldnt_remove_group());
      console.error(e);
    }
  });

  const changeRole = createAsyncState(async (newRole: SpaceRole["value"]) => {
    try {
      await eneo.spaces.groupMembers.update({
        spaceId: $currentSpace.id,
        group: { id: groupMember.id, role: newRole }
      });
      // Await refreshing as that will update the actual label
      await refreshCurrentSpace();
    } catch (e) {
      toastError(e, m.couldnt_change_role());
      console.error(e);
      selectedRole = groupMember.role;
    }
  });

  let showRemoveDialog = $state(false);
</script>

<div class="flex items-center gap-2">
  <Select.Root
    type="single"
    bind:value={selectedRole}
    onValueChange={(role) => changeRole(role as SpaceRole["value"])}
  >
    <Select.Trigger aria-label={m.select_role_for_group()} class="capitalize">
      {#if changeRole.isLoading}
        <IconLoadingSpinner class="animate-spin"></IconLoadingSpinner>
      {:else}
        {groupMember.role}
      {/if}
    </Select.Trigger>
    <Select.Content>
      {#each options as item (item.value)}
        <Select.Item value={item.value} label={item.value} class="capitalize">
          {item.value}
        </Select.Item>
      {/each}
    </Select.Content>
  </Select.Root>

  <Button
    variant="destructive"
    size="icon"
    aria-label={m.remove_group()}
    onclick={() => (showRemoveDialog = true)}
  >
    <IconTrash class="h-4 w-4" />
  </Button>
</div>

<AlertDialog.Root bind:open={showRemoveDialog}>
  <AlertDialog.Content class={dialogLayout.content("small")}>
    <AlertDialog.Header class={dialogLayout.header}>
      <AlertDialog.Title>{m.remove_group()}</AlertDialog.Title>
      <AlertDialog.Description
        >{m.confirm_remove_group({ groupName: groupMember.name })}</AlertDialog.Description
      >
    </AlertDialog.Header>
    <AlertDialog.Footer class={dialogLayout.footer}>
      <AlertDialog.Cancel>{m.cancel()}</AlertDialog.Cancel>
      <Button variant="destructive" onclick={removeGroupMember}
        >{removeGroupMember.isLoading ? m.removing() : m.remove()}</Button
      >
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
