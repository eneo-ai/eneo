<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { invalidate } from "$app/navigation";
  import { getIntric } from "$lib/core/Intric";
  import type { UserGroup, UserSparse } from "@intric/intric-js";
  import { Dialog, Button } from "@intric/ui";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte.ts";
  import { m } from "$lib/paraglide/messages";
  import { IconSearch } from "@intric/icons/search";
  import { IconTrash } from "@intric/icons/trash";
  import { IconCheck } from "@intric/icons/check";
  import MemberChip from "$lib/features/spaces/components/MemberChip.svelte";
  import { UserList } from "../../../spaces/[spaceId]/members/AddMember.svelte.ts";

  const intric = getIntric();

  type Props = {
    userGroup: UserGroup;
  };

  let { userGroup }: Props = $props();

  let showDialog = $state<Dialog.OpenState>();
  let userList = new UserList();
  let searchQuery = $state("");
  let selectedUsers = $state<UserSparse[]>([]);

  const memberIds = $derived((userGroup.users ?? []).map((u) => u.id));
  const selectedIds = $derived(selectedUsers.map((u) => u.id));

  let debounceTimeout: ReturnType<typeof setTimeout>;
  function handleSearch(value: string) {
    searchQuery = value;
    clearTimeout(debounceTimeout);
    debounceTimeout = setTimeout(() => {
      userList.setFilter(value);
    }, 250);
  }

  function toggleUserSelection(user: UserSparse) {
    const index = selectedUsers.findIndex((u) => u.id === user.id);
    if (index >= 0) {
      selectedUsers = selectedUsers.filter((u) => u.id !== user.id);
    } else {
      selectedUsers = [...selectedUsers, user];
    }
  }

  function clearSelection() {
    selectedUsers = [];
  }

  const addUsers = createAsyncState(async () => {
    if (selectedUsers.length === 0) return;
    try {
      for (const user of selectedUsers) {
        await intric.userGroups.addUser({ userGroup, user });
      }
      invalidate("admin:user-groups:load");
      selectedUsers = [];
      searchQuery = "";
    } catch (e) {
      alert(m.could_not_add_user_to_group());
      console.error(e);
    }
  });

  const removeUser = createAsyncState(async (user: UserSparse) => {
    try {
      await intric.userGroups.removeUser({ userGroup, user });
      invalidate("admin:user-groups:load");
    } catch (e) {
      alert(m.could_not_remove_user_from_group());
      console.error(e);
    }
  });
</script>

<Dialog.Root bind:isOpen={showDialog}>
  <Dialog.Trigger asFragment let:trigger>
    <Button variant="outlined" is={trigger}>{m.manage_members()}</Button>
  </Dialog.Trigger>

  <Dialog.Content width="large">
    <Dialog.Title>{m.manage_group_members_title({ groupName: userGroup.name })}</Dialog.Title>

    <Dialog.Section>
      <div class="border-default border-b px-4 py-4">
        <span class="text-primary mb-2 block font-medium">{m.add_user_to_group()}</span>

        <div class="relative mb-3">
          <input
            type="text"
            placeholder={m.find_user()}
            value={searchQuery}
            oninput={(e) => handleSearch(e.currentTarget.value)}
            class="border-stronger bg-primary ring-default placeholder:text-secondary
            h-10 w-full rounded-lg border px-3 py-2 pr-10 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
          />
          <IconSearch class="text-secondary absolute top-2.5 right-3 h-5 w-5" />
        </div>

        {#if selectedUsers.length > 0}
          <div class="mb-3 flex flex-wrap gap-2">
            {#each selectedUsers as user (user.id)}
              <button
                onclick={() => toggleUserSelection(user)}
                class="bg-accent-dimmer text-accent-default flex items-center gap-1 rounded-full px-3 py-1 text-sm hover:opacity-80"
              >
                {user.email}
                <span class="ml-1">&times;</span>
              </button>
            {/each}
          </div>
        {/if}

        <div class="border-default max-h-48 overflow-y-auto rounded-lg border">
          {#if userList.filteredUsers.length > 0}
            {#each userList.filteredUsers as userProxy (userProxy.id)}
              {@const user = $state.snapshot(userProxy)}
              {@const isMember = memberIds.includes(user.id)}
              {@const isSelected = selectedIds.includes(user.id)}
              <button
                onclick={() => !isMember && toggleUserSelection(user)}
                disabled={isMember}
                class="border-default flex w-full items-center gap-4 border-b px-4 py-2 text-left last:border-b-0
                  {isMember ? 'cursor-not-allowed opacity-50' : 'hover:bg-hover-dimmer cursor-pointer'}
                  {isSelected ? 'bg-accent-dimmer' : ''}"
              >
                <div class="border-stronger flex h-5 w-5 shrink-0 items-center justify-center rounded border {isSelected ? 'bg-accent-default border-accent-default' : 'bg-primary'}">
                  {#if isSelected}
                    <IconCheck class="h-3 w-3 text-white" />
                  {/if}
                </div>
                <MemberChip member={user}></MemberChip>
                <span class="text-primary flex-grow truncate">{user.email}</span>
                {#if isMember}
                  <span class="text-muted text-sm">({m.already_added()})</span>
                {/if}
              </button>
            {/each}
          {:else}
            <div class="text-secondary px-4 py-3 text-center">{m.no_users_found()}</div>
          {/if}
        </div>

        {#if userList.hasMoreUsers}
          <Button
            onclick={() => userList.loadMore()}
            variant="outlined"
            disabled={userList.isLoadingUsers}
            class="mt-2 w-full"
          >
            {#if userList.isLoadingUsers}
              {m.loading_more()}
            {:else}
              {m.load_more_users({
                current: userList.filteredUsers.length,
                total: userList.totalCount
              })}
            {/if}
          </Button>
        {/if}

        <div class="mt-3 flex justify-end gap-2">
          {#if selectedUsers.length > 0}
            <Button variant="outlined" on:click={clearSelection}>
              {m.clear_selection()}
            </Button>
          {/if}
          <Button
            variant="primary"
            disabled={selectedUsers.length === 0 || addUsers.isLoading}
            on:click={addUsers}
          >
            {addUsers.isLoading ? m.adding() : m.add_selected({ count: selectedUsers.length })}
          </Button>
        </div>
      </div>

      <div class="px-4 py-4">
        <span class="text-primary mb-2 block font-medium">{m.current_members()} ({userGroup.users?.length ?? 0})</span>
        <div class="border-default max-h-64 overflow-y-auto rounded-lg border">
          {#if (userGroup.users ?? []).length > 0}
            {#each userGroup.users ?? [] as user (user.id)}
              <div
                class="border-default hover:bg-hover-dimmer flex items-center justify-between gap-4 border-b px-4 py-3 last:border-b-0"
              >
                <div class="flex items-center gap-3">
                  <MemberChip member={{ ...user, role: "member" }}></MemberChip>
                  <div class="flex flex-col">
                    <span class="text-primary">{user.email}</span>
                    {#if user.username}
                      <span class="text-secondary text-sm">{user.username}</span>
                    {/if}
                  </div>
                </div>
                <Button
                  variant="destructive"
                  size="small"
                  on:click={() => removeUser(user)}
                  disabled={removeUser.isLoading}
                >
                  <IconTrash class="h-4 w-4" />
                </Button>
              </div>
            {/each}
          {:else}
            <div class="text-muted px-4 py-6 text-center">
              {m.no_users_in_group()}
            </div>
          {/if}
        </div>
      </div>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close}>{m.close()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
