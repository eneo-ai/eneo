<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconPeople } from "@eneo/icons/people";
  import type { UserGroup } from "@eneo/eneo-js";
  import { getEneo } from "$lib/core/Eneo";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import AddSpaceMemberDialog from "$lib/features/spaces/components/AddSpaceMemberDialog.svelte";
  import { m } from "$lib/paraglide/messages";

  const eneo = getEneo();
  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  let open = $state(false);
  let filter = $state("");
  let userGroups = $state<UserGroup[]>([]);
  const filteredGroups = $derived(
    userGroups.filter((group) => group.name.toLowerCase().includes(filter.toLowerCase()))
  );
  const groupIds = $derived($currentSpace.group_members?.items?.map((group) => group.id) ?? []);

  $effect(() => {
    if (open) {
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
</script>

<AddSpaceMemberDialog
  bind:open
  bind:filter
  triggerLabel={m.add_group()}
  title={m.add_group_to_space()}
  fieldLabel={m.user_group()}
  searchPlaceholder={m.find_group()}
  submitLabel={m.add_group()}
  errorContext={m.could_not_add_group()}
  emptyMessage={userGroups.length === 0 ? m.no_user_groups_found() : m.no_matching_groups_found()}
  items={filteredGroups}
  addedIds={groupIds}
  roles={$currentSpace.available_roles.map((role) => role.value)}
  getLabel={(group) => group.name}
  onAdd={(group, role) =>
    eneo.spaces.groupMembers.add({ spaceId: $currentSpace.id, group: { id: group.id, role } })}
  onAdded={() => refreshCurrentSpace()}
>
  {#snippet row(group, added)}
    <IconPeople class="text-secondary h-5 w-5" />
    <span class="text-primary truncate">{group.name}</span>
    {#if added}
      <span class="text-muted text-sm">({m.already_added()})</span>
    {/if}
  {/snippet}
</AddSpaceMemberDialog>
