<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconSearch } from "@eneo/icons/search";
  import { tick } from "svelte";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Command from "$lib/components/ui/command/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import { getEneo } from "$lib/core/Eneo";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import type { UserSparse } from "@eneo/eneo-js";
  import MemberChip from "$lib/features/spaces/components/MemberChip.svelte";
  import { UserList } from "$lib/features/users/user-list.svelte";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte.ts";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";

  const {
    refreshCurrentSpace,
    state: { currentSpace }
  } = getSpacesManager();

  const uid = $props.id();
  let userList = new UserList({});
  let selectedRole = $state.raw($currentSpace.available_roles[0]);
  let selectedUser = $state<UserSparse | undefined>();
  let filter = $state("");
  let pickerOpen = $state(false);
  let pickerTrigger = $state<HTMLButtonElement | null>(null);
  const memberIds = $derived($currentSpace.members.map((member) => member.id));
  const eneo = getEneo();
  let showDialog = $state(false);

  $effect(() => {
    userList.setFilter(filter);
  });

  function selectUser(user: UserSparse) {
    selectedUser = user;
    pickerOpen = false;
    filter = "";
    void tick().then(() => pickerTrigger?.focus());
  }

  const addMember = createAsyncState(async () => {
    const id = selectedUser?.id;
    if (!id) return;
    try {
      await eneo.spaces.members.add({
        spaceId: $currentSpace.id,
        user: { id, role: selectedRole.value }
      });
      refreshCurrentSpace();
      showDialog = false;
      selectedUser = undefined;
    } catch (e) {
      toastError(e, m.could_not_add_new_member());
      console.error(e);
    }
  });
</script>

{#snippet userLabel(user: UserSparse)}
  <MemberChip member={user}></MemberChip>
  <span class="text-primary truncate">{user.email}</span>
{/snippet}

<Dialog.Root bind:open={showDialog}>
  <Dialog.Trigger>
    {#snippet child({ props })}
      <Button {...props}>{m.add_new_member()}</Button>
    {/snippet}
  </Dialog.Trigger>

  <Dialog.Content class={dialogLayout.content("medium")} closeLabel={m.close()}>
    <form
      class="contents"
      onsubmit={(event) => {
        event.preventDefault();
        addMember();
      }}
    >
      <Dialog.Header class={dialogLayout.header}>
        <Dialog.Title>{m.add_new_member()}</Dialog.Title>
      </Dialog.Header>

      <div class={dialogLayout.body}>
        <div class={dialogLayout.section}>
          <div class="flex items-end gap-4 p-4">
            <Field.Field class="flex-grow">
              <Field.Label id={`${uid}-user-label`} for={`${uid}-user`}>{m.user()}</Field.Label>
              <Popover.Root bind:open={pickerOpen}>
                <Popover.Trigger>
                  {#snippet child({ props })}
                    <button
                      {...props}
                      bind:this={pickerTrigger}
                      id={`${uid}-user`}
                      aria-labelledby={`${uid}-user-label ${uid}-user`}
                      type="button"
                      class={buttonVariants({
                        variant: "outline",
                        class: "w-full justify-between font-normal"
                      })}
                    >
                      <span class="truncate" class:text-muted={!selectedUser}>
                        {selectedUser?.email ?? m.find_user()}
                      </span>
                      <IconSearch />
                    </button>
                  {/snippet}
                </Popover.Trigger>
                <Popover.Content align="start" class="w-(--bits-popover-anchor-width) p-0">
                  <Command.Root shouldFilter={false}>
                    <Command.Input bind:value={filter} placeholder={m.find_user()} />
                    <Command.List>
                      {#each userList.filteredUsers as userProxy (userProxy.id)}
                        {@const user = $state.snapshot(userProxy)}
                        {@const isMember = memberIds.includes(user.id)}
                        <Command.Item
                          value={user.id}
                          disabled={isMember}
                          onSelect={() => selectUser(user)}
                        >
                          {#if isMember}
                            <Tooltip.Root>
                              <Tooltip.Trigger>
                                {#snippet child({ props })}
                                  {@const { tabindex: _tabindex, ...triggerProps } = props}
                                  <div
                                    {...triggerProps}
                                    class="pointer-events-auto flex w-full items-center gap-2"
                                  >
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
                        </Command.Item>
                      {:else}
                        <p class="text-secondary px-2 py-1.5 text-sm">
                          {m.no_matching_users_found()}
                        </p>
                      {/each}
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
                    </Command.List>
                  </Command.Root>
                </Popover.Content>
              </Popover.Root>
            </Field.Field>

            <Field.Field class="w-1/3">
              <Field.Label for={`${uid}-role`}>{m.role()}</Field.Label>
              <Select.Root
                type="single"
                value={selectedRole.value}
                onValueChange={(value) => {
                  selectedRole =
                    $currentSpace.available_roles.find((role) => role.value === value) ??
                    selectedRole;
                }}
              >
                <Select.Trigger id={`${uid}-role`} class="w-full"
                  >{selectedRole.label}</Select.Trigger
                >
                <Select.Content>
                  {#each $currentSpace.available_roles as role (role.value)}
                    <Select.Item value={role.value} label={role.label}>{role.label}</Select.Item>
                  {/each}
                </Select.Content>
              </Select.Root>
            </Field.Field>
          </div>
        </div>
      </div>

      <Dialog.Footer class={dialogLayout.footer}>
        <Dialog.Close class={buttonVariants({ variant: "outline" })}>{m.cancel()}</Dialog.Close>
        <Button type="submit" disabled={!selectedUser || addMember.isLoading}>
          {addMember.isLoading ? m.adding() : m.add_member()}
        </Button>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
