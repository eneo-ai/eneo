<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import { IconTrash } from "@eneo/icons/trash";
  import type { Space, SpaceRole } from "@eneo/eneo-js";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import { toastError } from "$lib/core/errors";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { m } from "$lib/paraglide/messages";

  type Props =
    | { kind: "user"; member: Space["members"]["items"][number] }
    | { kind: "group"; member: Space["group_members"]["items"][number] };

  const props: Props = $props();

  const eneo = getEneo();
  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  // The member prop stays the source of truth: a failed change resets to it, a successful one refreshes it.
  let selectedRole = $derived(props.member.role);

  const labels = $derived(
    props.kind === "group"
      ? {
          select: m.select_role_for_group(),
          remove: m.remove_group(),
          confirmRemove: m.confirm_remove_group({ groupName: props.member.name }),
          removeError: m.couldnt_remove_group()
        }
      : {
          select: m.select_role_for_member(),
          remove: m.remove_member(),
          confirmRemove: m.confirm_remove_member({ memberEmail: props.member.email }),
          removeError: m.couldnt_remove_user()
        }
  );

  async function remove() {
    const spaceId = $currentSpace.id;
    if (props.kind === "group") {
      await eneo.spaces.groupMembers.remove({ spaceId, group: props.member });
    } else {
      await eneo.spaces.members.remove({ spaceId, user: props.member });
    }
    refreshCurrentSpace();
  }

  const changeRole = createAsyncState(async (role: SpaceRole["value"]) => {
    const spaceId = $currentSpace.id;
    const id = props.member.id;
    try {
      if (props.kind === "group") {
        await eneo.spaces.groupMembers.update({ spaceId, group: { id, role } });
      } else {
        await eneo.spaces.members.update({ spaceId, user: { id, role } });
      }
      // Awaited so the spinner stays until the refreshed member prop carries the new role.
      await refreshCurrentSpace();
    } catch (e) {
      toastError(e, m.couldnt_change_role());
      console.error(e);
      selectedRole = props.member.role;
    }
  });
</script>

<div class="flex items-center gap-2">
  <Select.Root
    type="single"
    bind:value={selectedRole}
    onValueChange={(role) => changeRole(role as SpaceRole["value"])}
  >
    <Select.Trigger aria-label={labels.select} class="capitalize">
      {#if changeRole.isLoading}
        <IconLoadingSpinner class="animate-spin"></IconLoadingSpinner>
      {:else}
        {props.member.role}
      {/if}
    </Select.Trigger>
    <Select.Content>
      {#each $currentSpace.available_roles as role (role.value)}
        <Select.Item value={role.value} label={role.value} class="capitalize">
          {role.value}
        </Select.Item>
      {/each}
    </Select.Content>
  </Select.Root>

  <ConfirmDialog
    title={labels.remove}
    description={labels.confirmRemove}
    confirmLabel={m.remove()}
    pendingLabel={m.removing()}
    errorContext={labels.removeError}
    onConfirm={remove}
  >
    {#snippet trigger({ props: triggerProps })}
      <Button {...triggerProps} variant="destructive" size="icon" aria-label={labels.remove}>
        <IconTrash class="h-4 w-4" />
      </Button>
    {/snippet}
  </ConfirmDialog>
</div>
