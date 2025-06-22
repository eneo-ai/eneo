<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconSearch } from "@intric/icons/search";
  import { Button, Dialog, Select, Tooltip } from "@intric/ui";
  import { getIntric } from "$lib/core/Intric";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import type { UserSparse } from "@intric/intric-js";
  import { createCombobox } from "@melt-ui/svelte";
  import MemberChip from "$lib/features/spaces/components/MemberChip.svelte";
  import { UserList } from "./AddMember.svelte.ts";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte.ts";
  import { m } from "$lib/paraglide/messages";

  const {
    refreshCurrentSpace,
    state: { currentSpace }
  } = getSpacesManager();

  const {
    elements: { menu, input, option },
    states: { open, inputValue, selected }
  } = createCombobox<UserSparse>({
    portal: null,
    positioning: {
      sameWidth: true,
      fitViewport: true,
      placement: "bottom"
    }
  });

  let userList = new UserList();
  let selectedRole = $state.raw($currentSpace.available_roles[0]);
  const memberIds = $derived($currentSpace.members.map((member) => member.id));
  const intric = getIntric();
  let inputElement: HTMLInputElement;
  let showDialog = $state<Dialog.OpenState>();

  inputValue.subscribe((filter) => userList.setFilter(filter));
  open.subscribe((isOpen) => {
    if (!isOpen) {
      $inputValue = $selected?.value.email ?? "";
    }
  });

  const addMember = createAsyncState(async () => {
    const id = $selected?.value.id;
    if (!id) return;
    try {
      await intric.spaces.members.add({
        spaceId: $currentSpace.id,
        user: { id, role: selectedRole.value }
      });
      refreshCurrentSpace();
      $showDialog = false;
      $selected = undefined;
    } catch (e) {
      alert(m.could_not_add_new_member());
      console.error(e);
    }
  });
</script>

<Dialog.Root bind:isOpen={showDialog}>
  <Dialog.Trigger asFragment let:trigger>
    <Button variant="primary" is={trigger}>{m.add_new_member()}</Button>
  </Dialog.Trigger>

  <Dialog.Content width="medium" form>
    <Dialog.Title>{m.add_new_member()}</Dialog.Title>

    <Dialog.Section scrollable={false}>
      <div class="hover:bg-hover-dimmer flex items-center rounded-md">
        <div class="flex flex-grow flex-col gap-1 rounded-md pt-2 pr-2 pb-4 pl-4">
          <div>
            <span class="pl-3 font-medium">{m.user()}</span>
          </div>

          <div class="relative flex flex-grow">
            <input
              bind:this={inputElement}
              placeholder={m.find_user()}
              {...$input}
              required
              use:input
              class="border-stronger bg-primary ring-default placeholder:text-secondary disabled:bg-secondary disabled:text-muted relative
            h-10 w-full items-center justify-between overflow-hidden rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2 disabled:shadow-none disabled:hover:ring-0"
            />
            <button
              onclick={() => {
                inputElement.focus();
                $open = true;
              }}
            >
              <IconSearch class="absolute top-2 right-4" />
            </button>
          </div>
          <ul
            class="shadow-bg-secondary border-stronger bg-primary relative z-10 flex flex-col gap-1 overflow-y-auto rounded-lg border p-1 shadow-md focus:!ring-0"
            {...$menu}
            use:menu
          >
            <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
            <div class="bg-primary text-primary flex flex-col gap-0" tabindex="0">
              {#if userList.filteredUsers.length > 0}
                {#each userList.filteredUsers as userProxy (userProxy.id)}
                  {@const user = $state.snapshot(userProxy)}
                  {@const isMember = memberIds.includes(user.id)}
                  <li
                    {...$option({
                      value: user,
                      label: user.email,
                      disabled: isMember
                    })}
                    use:option
                    class="hover:bg-hover-default data-[highlighted]:bg-secondary flex items-center gap-1 rounded-md px-2 py-1 hover:cursor-pointer data-[disabled]:pointer-events-none data-[disabled]:!cursor-not-allowed data-[disabled]:opacity-30 data-[disabled]:hover:bg-transparent"
                    class:opacity-70={isMember}
                  >
                    <Tooltip
                      text={isMember
                        ? m.user_already_member({ space: $currentSpace.name })
                        : undefined}
                      class="pointer-events-auto flex w-full"
                    >
                      <div class="px-2">
                        <MemberChip member={user}></MemberChip>
                      </div>

                      <span class=" text-primary truncate py-1">
                        {user.email}
                      </span>
                    </Tooltip>
                  </li>
                {/each}
              {:else}
                <span class="text-secondary px-2 py-1">{m.no_matching_users_found()}</span>
              {/if}
            </div>
            {#if userList.hasMoreUsers}
              <Button
                onclick={() => userList.loadMore()}
                variant="outlined"
                disabled={userList.isLoadingUsers}
              >
                {#if userList.isLoadingUsers}
                  {m.loading_more()}
                {:else}
                  {m.load_more_users({ current: userList.filteredUsers.length, total: userList.totalCount })}
                {/if}
              </Button>
            {/if}
          </ul>
        </div>
        <Select.Simple
          fitViewport={true}
          class="w-1/3  p-4 pl-2 "
          options={$currentSpace.available_roles.map((role) => {
            return { label: role.label, value: role };
          })}
          bind:value={selectedRole}>{m.role()}</Select.Simple
        >
      </div>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>

      <Button variant="primary" on:click={addMember} type="submit"
        >{addMember.isLoading ? m.adding() : m.add_member()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
