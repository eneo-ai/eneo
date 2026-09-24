<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconTrash } from "@eneo/icons/trash";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
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

  async function removeGroupMember() {
    await eneo.spaces.groupMembers.remove({ spaceId: $currentSpace.id, group: groupMember });
    // Will cause an update in the parent page and remove this component instance from the tree
    refreshCurrentSpace();
  }

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

  <ConfirmDialog
    title={m.remove_group()}
    description={m.confirm_remove_group({ groupName: groupMember.name })}
    confirmLabel={m.remove()}
    pendingLabel={m.removing()}
    errorContext={m.couldnt_remove_group()}
    onConfirm={removeGroupMember}
  >
    {#snippet trigger({ props })}
      <Button {...props} variant="destructive" size="icon" aria-label={m.remove_group()}>
        <IconTrash class="h-4 w-4" />
      </Button>
    {/snippet}
  </ConfirmDialog>
</div>
