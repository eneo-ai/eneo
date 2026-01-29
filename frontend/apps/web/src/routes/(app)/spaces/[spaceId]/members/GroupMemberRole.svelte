<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconChevronDown } from "@intric/icons/chevron-down";
  import { IconSelectedItem } from "@intric/icons/selected-item";
  import { IconTrash } from "@intric/icons/trash";
  import { Button, Dialog } from "@intric/ui";
  import { getIntric } from "$lib/core/Intric";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import type { Space, SpaceRole } from "@intric/intric-js";
  import { createSelect } from "@melt-ui/svelte";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { m } from "$lib/paraglide/messages";

  type GroupMember = Space["group_members"]["items"][number];
  type RoleOption = { label: string; value: SpaceRole["value"] };

  type Props = {
    groupMember: GroupMember;
  };

  let { groupMember }: Props = $props();
  const intric = getIntric();

  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  const options: RoleOption[] = $currentSpace.available_roles.filter(role => role.value !== "owner");

  const {
    elements: { trigger, menu, option, label },
    states: { selected },
    helpers: { isSelected }
  } = createSelect({
    positioning: {
      placement: "bottom",
      fitViewport: true,
      sameWidth: false
    },
    defaultSelected: { value: groupMember.role }
  });

  // After changing the role we update with the passed prop as source of truth
  $effect(() => {
    $selected = { value: groupMember.role };
  });

  const removeGroupMember = createAsyncState(async () => {
    try {
      await intric.spaces.groupMembers.remove({ spaceId: $currentSpace.id, group: groupMember });
      $showRemoveDialog = false;
      // Will cause an update in the parent page and remove this component instance from the tree
      refreshCurrentSpace();
    } catch (e) {
      alert(m.couldnt_remove_group());
      console.error(e);
    }
  });

  const changeRole = createAsyncState(async (newRole: SpaceRole["value"]) => {
    try {
      await intric.spaces.groupMembers.update({
        spaceId: $currentSpace.id,
        group: { id: groupMember.id, role: newRole }
      });
      // Await refreshing as that will update the actual label
      await refreshCurrentSpace();
    } catch (e) {
      alert(m.couldnt_change_role());
      console.error(e);
      // Reset selected
      $selected = { value: groupMember.role };
    }
  });

  async function handleMenuOption(option: RoleOption["value"]) {
    changeRole(option);
  }

  let showRemoveDialog = $state<Dialog.OpenState>();
</script>

<div class="flex items-center gap-2">
  <div class="relative flex flex-col gap-1">
    <label class="sr-only pl-3 font-medium" {...$label} use:label>
      {m.select_role_for_group()}
    </label>

    <Button is={[$trigger]}>
      <div class="truncate capitalize">
        {#if changeRole.isLoading}
          <IconLoadingSpinner class="animate-spin"></IconLoadingSpinner>
        {:else}
          {groupMember.role}
        {/if}
      </div>
      <IconChevronDown />
    </Button>

    <div
      class="border-stronger bg-primary z-10 flex flex-col gap-1 overflow-y-auto rounded-lg border p-1 shadow-md focus:!ring-0"
      {...$menu}
      use:menu
    >
      {#each options as item (item.value)}
        <div
          class="text-primary hover:bg-hover-default data-[highlighted]:bg-secondary flex items-center gap-1 rounded-md hover:cursor-pointer data-[disabled]:opacity-30 data-[disabled]:hover:bg-transparent"
          {...$option({ value: item.value })}
          use:option
        >
          <Button
            class="w-full !justify-start capitalize"
            variant="simple"
            on:click={() => {
              handleMenuOption(item.value);
            }}
          >
            <span>
              {item.value}
            </span>
            {#if $isSelected(item.value)}
              <IconSelectedItem class="text-accent-default" />
            {/if}
          </Button>
        </div>
      {/each}
    </div>
  </div>

  <Button
    variant="destructive"
    padding="icon"
    label={m.remove_group()}
    on:click={() => ($showRemoveDialog = true)}
  >
    <IconTrash class="h-4 w-4" />
  </Button>
</div>

<Dialog.Root alert bind:isOpen={showRemoveDialog}>
  <Dialog.Content width="small">
    <Dialog.Title>{m.remove_group()}</Dialog.Title>
    <Dialog.Description>{m.confirm_remove_group({ groupName: groupMember.name })}</Dialog.Description>
    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="destructive" on:click={removeGroupMember}
        >{removeGroupMember.isLoading ? m.removing() : m.remove()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
