<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { UserSparse } from "@eneo/eneo-js";
  import * as Command from "$lib/components/ui/command/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import AddSpaceMemberDialog from "$lib/features/spaces/components/AddSpaceMemberDialog.svelte";
  import MemberChip from "$lib/features/spaces/components/MemberChip.svelte";
  import { UserList } from "$lib/features/users/user-list.svelte";
  import { m } from "$lib/paraglide/messages";

  const eneo = getEneo();
  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  const userList = new UserList({});
  let filter = $state("");
  const memberIds = $derived($currentSpace.members.map((member) => member.id));

  $effect(() => {
    userList.setFilter(filter);
  });
</script>

{#snippet userLabel(user: UserSparse)}
  <MemberChip member={user}></MemberChip>
  <span class="text-primary truncate">{user.email}</span>
{/snippet}

<AddSpaceMemberDialog
  bind:filter
  triggerLabel={m.add_new_member()}
  title={m.add_new_member()}
  fieldLabel={m.user()}
  searchPlaceholder={m.find_user()}
  submitLabel={m.add_member()}
  errorContext={m.could_not_add_new_member()}
  emptyMessage={m.no_matching_users_found()}
  items={userList.filteredUsers}
  addedIds={memberIds}
  roles={$currentSpace.available_roles.map((role) => role.value)}
  getLabel={(user) => user.email}
  onAdd={(user, role) =>
    eneo.spaces.members.add({ spaceId: $currentSpace.id, user: { id: user.id, role } })}
  onAdded={() => refreshCurrentSpace()}
>
  {#snippet row(user, added)}
    {#if added}
      <Tooltip.Root>
        <Tooltip.Trigger>
          {#snippet child({ props })}
            {@const { tabindex: _tabindex, ...triggerProps } = props}
            <div {...triggerProps} class="pointer-events-auto flex w-full items-center gap-2">
              {@render userLabel(user)}
            </div>
          {/snippet}
        </Tooltip.Trigger>
        <Tooltip.Content>
          {m.user_already_member({ space: $currentSpace.name })}
        </Tooltip.Content>
      </Tooltip.Root>
    {:else}
      {@render userLabel(user)}
    {/if}
  {/snippet}

  {#snippet listEnd()}
    {#if userList.hasMoreUsers}
      <Command.Item
        value="load-more"
        disabled={userList.isLoadingUsers}
        onSelect={() => userList.loadMore()}
        class="justify-center"
      >
        {#if userList.isLoadingUsers}
          {m.loading_more()}
        {:else}
          {m.load_more_users({
            current: userList.filteredUsers.length,
            total: userList.totalCount
          })}
        {/if}
      </Command.Item>
    {/if}
  {/snippet}
</AddSpaceMemberDialog>
