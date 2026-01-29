<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconSearch } from "@intric/icons/search";
  import { Button, Dialog, Select } from "@intric/ui";
  import { getIntric } from "$lib/core/Intric";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import type { UserGroup } from "@intric/intric-js";
  import { createCombobox } from "@melt-ui/svelte";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte.ts";
  import { m } from "$lib/paraglide/messages";
  import { IconGroup } from "@intric/icons/group";

  const {
    refreshCurrentSpace,
    state: { currentSpace }
  } = getSpacesManager();

  const {
    elements: { menu, input, option },
    states: { open, inputValue, selected }
  } = createCombobox<UserGroup>({
    portal: null,
    positioning: {
      sameWidth: true,
      fitViewport: true,
      placement: "bottom"
    }
  });

  let userGroups = $state<UserGroup[]>([]);
  let filteredGroups = $derived(
    userGroups.filter((group) =>
      group.name.toLowerCase().includes($inputValue.toLowerCase())
    )
  );
  let selectedRole = $state.raw(
    $currentSpace.available_roles.find(r => r.value !== "owner") ?? $currentSpace.available_roles[0]
  );
  const existingGroupIds = $derived($currentSpace.group_members?.items?.map((g) => g.id) ?? []);
  const intric = getIntric();
  let inputElement: HTMLInputElement;
  let showDialog = $state<Dialog.OpenState>();

  $effect(() => {
    if (showDialog) {
      loadUserGroups();
    }
  });

  open.subscribe((isOpen) => {
    if (!isOpen) {
      $inputValue = $selected?.value.name ?? "";
    }
  });

  async function loadUserGroups() {
    try {
      userGroups = await intric.userGroups.list();
    } catch (e) {
      console.error("Failed to load user groups", e);
      userGroups = [];
    }
  }

  const addGroupMember = createAsyncState(async () => {
    const id = $selected?.value.id;
    if (!id) return;
    try {
      await intric.spaces.groupMembers.add({
        spaceId: $currentSpace.id,
        group: { id, role: selectedRole.value }
      });
      refreshCurrentSpace();
      $showDialog = false;
      $selected = undefined;
    } catch (e) {
      alert(m.could_not_add_group());
      console.error(e);
    }
  });
</script>

<Dialog.Root bind:isOpen={showDialog}>
  <Dialog.Trigger asFragment let:trigger>
    <Button variant="primary" is={trigger}>{m.add_group()}</Button>
  </Dialog.Trigger>

  <Dialog.Content width="medium" form>
    <Dialog.Title>{m.add_group_to_space()}</Dialog.Title>

    <Dialog.Section scrollable={false}>
      <div class="hover:bg-hover-dimmer flex items-center rounded-md">
        <div class="flex flex-grow flex-col gap-1 rounded-md pt-2 pr-2 pb-4 pl-4">
          <div>
            <span class="pl-3 font-medium">{m.user_group()}</span>
          </div>

          <div class="relative flex flex-grow">
            <input
              bind:this={inputElement}
              placeholder={m.find_group()}
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
              {#if filteredGroups.length > 0}
                {#each filteredGroups as group (group.id)}
                  {@const isMember = existingGroupIds.includes(group.id)}
                  <li
                    {...$option({
                      value: group,
                      label: group.name,
                      disabled: isMember
                    })}
                    use:option
                    class="hover:bg-hover-default data-[highlighted]:bg-secondary flex items-center gap-1 rounded-md px-2 py-1 hover:cursor-pointer data-[disabled]:pointer-events-none data-[disabled]:!cursor-not-allowed data-[disabled]:opacity-30 data-[disabled]:hover:bg-transparent"
                    class:opacity-70={isMember}
                  >
                    <div class="flex w-full items-center gap-2 px-2 py-1">
                      <IconGroup class="h-5 w-5 text-secondary" />
                      <span class="text-primary truncate">
                        {group.name}
                      </span>
                      {#if isMember}
                        <span class="text-muted text-sm">({m.already_added()})</span>
                      {/if}
                    </div>
                  </li>
                {/each}
              {:else if userGroups.length === 0}
                <span class="text-secondary px-2 py-1">{m.no_user_groups_found()}</span>
              {:else}
                <span class="text-secondary px-2 py-1">{m.no_matching_groups_found()}</span>
              {/if}
            </div>
          </ul>
        </div>
        <Select.Simple
          fitViewport={true}
          class="w-1/3 p-4 pl-2"
          options={$currentSpace.available_roles
            .filter(role => role.value !== "owner")
            .map((role) => {
              return { label: role.label, value: role };
            })}
          bind:value={selectedRole}>{m.role()}</Select.Simple
        >
      </div>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>

      <Button variant="primary" on:click={addGroupMember} type="submit"
        >{addGroupMember.isLoading ? m.adding() : m.add_group()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
