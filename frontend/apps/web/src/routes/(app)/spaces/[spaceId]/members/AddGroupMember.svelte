<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconSearch } from "@eneo/icons/search";
  import { IconPeople } from "@eneo/icons/people";
  import { tick } from "svelte";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Command from "$lib/components/ui/command/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import { getEneo } from "$lib/core/Eneo";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import type { UserGroup } from "@eneo/eneo-js";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte.ts";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";

  const {
    refreshCurrentSpace,
    state: { currentSpace }
  } = getSpacesManager();

  const uid = $props.id();
  let userGroups = $state<UserGroup[]>([]);
  let filter = $state("");
  let filteredGroups = $derived(
    userGroups.filter((group) => group.name.toLowerCase().includes(filter.toLowerCase()))
  );
  let selectedRole = $state.raw($currentSpace.available_roles[0]);
  let selectedGroup = $state<UserGroup | undefined>();
  let pickerOpen = $state(false);
  let pickerTrigger = $state<HTMLButtonElement | null>(null);
  const existingGroupIds = $derived($currentSpace.group_members?.items?.map((g) => g.id) ?? []);
  const eneo = getEneo();
  let showDialog = $state(false);

  $effect(() => {
    if (showDialog) {
      loadUserGroups();
    }
  });

  async function loadUserGroups() {
    try {
      userGroups = await eneo.userGroups.list();
    } catch (e) {
      console.error("Failed to load user groups", e);
      userGroups = [];
    }
  }

  function selectGroup(group: UserGroup) {
    selectedGroup = group;
    pickerOpen = false;
    filter = "";
    void tick().then(() => pickerTrigger?.focus());
  }

  const addGroupMember = createAsyncState(async () => {
    if (!selectedGroup) return;
    try {
      await eneo.spaces.groupMembers.add({
        spaceId: $currentSpace.id,
        group: { id: selectedGroup.id, role: selectedRole.value }
      });
      refreshCurrentSpace();
      showDialog = false;
      selectedGroup = undefined;
    } catch (e) {
      toastError(e, m.could_not_add_group());
      console.error(e);
    }
  });
</script>

<Dialog.Root bind:open={showDialog}>
  <Dialog.Trigger>
    {#snippet child({ props })}
      <Button {...props}>{m.add_group()}</Button>
    {/snippet}
  </Dialog.Trigger>

  <Dialog.Content class={dialogLayout.content("medium")} closeLabel={m.close()}>
    <form
      class="contents"
      onsubmit={(event) => {
        event.preventDefault();
        addGroupMember();
      }}
    >
      <Dialog.Header class={dialogLayout.header}>
        <Dialog.Title>{m.add_group_to_space()}</Dialog.Title>
      </Dialog.Header>

      <div class={dialogLayout.body}>
        <div class={dialogLayout.section}>
          <div class="flex items-end gap-4 p-4">
            <Field.Field class="flex-grow">
              <Field.Label id={`${uid}-group-label`} for={`${uid}-group`}
                >{m.user_group()}</Field.Label
              >
              <Popover.Root bind:open={pickerOpen}>
                <Popover.Trigger>
                  {#snippet child({ props })}
                    <button
                      {...props}
                      bind:this={pickerTrigger}
                      id={`${uid}-group`}
                      aria-labelledby={`${uid}-group-label ${uid}-group`}
                      type="button"
                      class={buttonVariants({
                        variant: "outline",
                        class: "w-full justify-between font-normal"
                      })}
                    >
                      <span class="truncate" class:text-muted={!selectedGroup}>
                        {selectedGroup?.name ?? m.find_group()}
                      </span>
                      <IconSearch />
                    </button>
                  {/snippet}
                </Popover.Trigger>
                <Popover.Content align="start" class="w-(--bits-popover-anchor-width) p-0">
                  <Command.Root shouldFilter={false}>
                    <Command.Input bind:value={filter} placeholder={m.find_group()} />
                    <Command.List>
                      {#each filteredGroups as group (group.id)}
                        {@const isMember = existingGroupIds.includes(group.id)}
                        <Command.Item
                          value={group.id}
                          disabled={isMember}
                          onSelect={() => selectGroup(group)}
                        >
                          <IconPeople class="text-secondary h-5 w-5" />
                          <span class="text-primary truncate">{group.name}</span>
                          {#if isMember}
                            <span class="text-muted text-sm">({m.already_added()})</span>
                          {/if}
                        </Command.Item>
                      {:else}
                        <p class="text-secondary px-2 py-1.5 text-sm">
                          {userGroups.length === 0
                            ? m.no_user_groups_found()
                            : m.no_matching_groups_found()}
                        </p>
                      {/each}
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
        <Button type="submit" disabled={!selectedGroup || addGroupMember.isLoading}>
          {addGroupMember.isLoading ? m.adding() : m.add_group()}
        </Button>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
