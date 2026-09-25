<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { Space, SpaceRoleValue } from "@eneo/eneo-js";
  import { IconPeople } from "@eneo/icons/people";
  import { Page, Settings } from "$lib/components/layout";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { getAppContext } from "$lib/core/AppContext";
  import { getEneo } from "$lib/core/Eneo";
  import { toastError } from "$lib/core/errors";
  import { formatDateMedium } from "$lib/core/formatting/dateTime";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import MemberChip from "$lib/features/spaces/components/MemberChip.svelte";
  import SpaceMemberRole from "$lib/features/spaces/components/SpaceMemberRole.svelte";
  import { spaceRoleLabel } from "$lib/features/spaces/roles";
  import { m } from "$lib/paraglide/messages";
  import AddGroupMember from "./AddGroupMember.svelte";
  import AddMember from "./AddMember.svelte";

  const { user } = getAppContext();
  const eneo = getEneo();

  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  const roles = $derived($currentSpace.available_roles.map((role) => role.value));
  const isViewerRoleAvailable = $derived(roles.includes("viewer"));
  const editors = $derived(
    $currentSpace.members.filter((member) => member.role === "admin" || member.role === "editor")
  );
  const viewers = $derived($currentSpace.members.filter((member) => member.role === "viewer"));
  const groupMembers = $derived($currentSpace.group_members?.items ?? []);

  async function changeRole(kind: "user" | "group", id: string, role: SpaceRoleValue) {
    const spaceId = $currentSpace.id;
    try {
      if (kind === "group") {
        await eneo.spaces.groupMembers.update({ spaceId, group: { id, role } });
      } else {
        await eneo.spaces.members.update({ spaceId, user: { id, role } });
      }
    } catch (error) {
      toastError(error, m.couldnt_change_role());
      throw error;
    }
    await refreshCurrentSpace();
  }

  async function removeUser(member: Space["members"]["items"][number]) {
    await eneo.spaces.members.remove({ spaceId: $currentSpace.id, user: member });
    await refreshCurrentSpace();
  }

  async function removeGroup(group: NonNullable<Space["group_members"]>["items"][number]) {
    await eneo.spaces.groupMembers.remove({ spaceId: $currentSpace.id, group });
    await refreshCurrentSpace();
  }
</script>

<svelte:head>
  <title>{m.app_name()} – {$currentSpace.name} – {m.members()}</title>
</svelte:head>

{#snippet memberRow(member: Space["members"]["items"][number])}
  <div
    class="border-default hover:bg-hover-dimmer flex flex-wrap items-center gap-x-4 gap-y-2 border-b py-4 pr-4 pl-4"
  >
    <MemberChip {member}></MemberChip>
    <div class="flex min-w-0 flex-1 flex-col gap-1">
      {#if user.id === member.id}
        <span class="text-primary break-words">{member.email} ({m.you()})</span>
      {:else}
        <span class="text-primary break-words">{member.email}</span>
      {/if}
      {#if member.oversight_join}
        <!-- Everyone sees who joined through oversight; only the space's admins get the reason. -->
        <div class="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
          <Badge variant="outline" class="h-auto whitespace-normal">
            {m.space_oversight_member_badge({
              date: formatDateMedium(member.oversight_join.joined_at)
            })}
          </Badge>
          {#if member.oversight_join.reason}
            <span class="text-secondary break-words">
              {m.space_oversight_notice_reason({ reason: member.oversight_join.reason })}
            </span>
          {/if}
        </div>
      {/if}
    </div>
    {#if $currentSpace.hasPermission("edit", "member") && user.id !== member.id}
      <SpaceMemberRole
        name={member.email}
        role={member.role}
        {roles}
        onChangeRole={(role) => changeRole("user", member.id, role)}
        onRemove={() => removeUser(member)}
        removeTitle={m.remove_member()}
        removeDescription={m.confirm_remove_member({ memberEmail: member.email })}
        removeErrorContext={m.couldnt_remove_user()}
      ></SpaceMemberRole>
    {:else}
      <span class="text-secondary px-2">{spaceRoleLabel(member.role)}</span>
    {/if}
  </div>
{/snippet}

{#snippet emptyRow(message: string)}
  <div
    class="border-default text-muted hover:bg-hover-dimmer flex items-center justify-between gap-4 border-b py-4 pr-4 pl-4"
  >
    {message}
  </div>
{/snippet}

<Page.Root>
  <Page.Header>
    <Page.Title title={m.members()}></Page.Title>
    <Page.Flex>
      {#if $currentSpace.hasPermission("add", "group_member")}
        <AddGroupMember></AddGroupMember>
      {/if}
      {#if $currentSpace.hasPermission("add", "member")}
        <AddMember></AddMember>
      {/if}
    </Page.Flex>
  </Page.Header>
  <Page.Main>
    <Settings.Page>
      <Settings.Group title={m.current_members()}>
        <Settings.Row title={m.admins_editors()} description={m.admins_editors_description()}>
          <div class="flex flex-grow flex-col">
            {#each editors as member (member.id)}
              {@render memberRow(member)}
            {/each}
          </div>
        </Settings.Row>

        {#if isViewerRoleAvailable}
          <Settings.Row title={m.viewers()} description={m.viewers_description()}>
            <div class="flex flex-grow flex-col">
              {#each viewers as member (member.id)}
                {@render memberRow(member)}
              {:else}
                {@render emptyRow(m.no_viewers_in_space())}
              {/each}
            </div>
          </Settings.Row>
        {/if}
      </Settings.Group>

      <Settings.Group title={m.group_members()}>
        <Settings.Row title={m.user_groups()} description={m.user_groups_description()}>
          <div class="flex flex-grow flex-col">
            {#each groupMembers as groupMember (groupMember.id)}
              <div
                class="border-default hover:bg-hover-dimmer flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b py-4 pr-4 pl-4"
              >
                <div class="flex min-w-0 items-center gap-2">
                  <IconPeople class="text-secondary h-6 w-6" />
                  <span class="text-primary font-medium">{groupMember.name}</span>
                </div>
                <span class="text-secondary text-sm">
                  {groupMember.user_count}
                  {groupMember.user_count === 1 ? m.user() : m.users()}
                </span>
                <div class="flex-grow"></div>
                {#if $currentSpace.hasPermission("edit", "group_member")}
                  <SpaceMemberRole
                    name={groupMember.name}
                    role={groupMember.role}
                    {roles}
                    onChangeRole={(role) => changeRole("group", groupMember.id, role)}
                    onRemove={() => removeGroup(groupMember)}
                    removeTitle={m.remove_group()}
                    removeDescription={m.confirm_remove_group({ groupName: groupMember.name })}
                    removeErrorContext={m.couldnt_remove_group()}
                  ></SpaceMemberRole>
                {:else}
                  <span class="text-secondary px-2">{spaceRoleLabel(groupMember.role)}</span>
                {/if}
              </div>
            {:else}
              {@render emptyRow(m.no_group_members_in_space())}
            {/each}
          </div>
        </Settings.Row>
      </Settings.Group>
    </Settings.Page>
  </Page.Main>
</Page.Root>
