<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { Space } from "@eneo/eneo-js";
  import { IconPeople } from "@eneo/icons/people";
  import { Page, Settings } from "$lib/components/layout";
  import { getAppContext } from "$lib/core/AppContext";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import MemberChip from "$lib/features/spaces/components/MemberChip.svelte";
  import SpaceMemberRole from "$lib/features/spaces/components/SpaceMemberRole.svelte";
  import { m } from "$lib/paraglide/messages";
  import AddGroupMember from "./AddGroupMember.svelte";
  import AddMember from "./AddMember.svelte";

  const { user } = getAppContext();

  const {
    state: { currentSpace }
  } = getSpacesManager();

  const isViewerRoleAvailable = $derived(
    $currentSpace.available_roles.some((role) => role.value === "viewer")
  );
  const editors = $derived(
    $currentSpace.members.filter((member) => member.role === "admin" || member.role === "editor")
  );
  const viewers = $derived($currentSpace.members.filter((member) => member.role === "viewer"));
  const groupMembers = $derived($currentSpace.group_members?.items ?? []);
</script>

<svelte:head>
  <title>{m.app_name()} – {$currentSpace.name} – {m.members()}</title>
</svelte:head>

{#snippet memberRow(member: Space["members"]["items"][number])}
  <div
    class="border-default hover:bg-hover-dimmer flex items-center justify-between gap-4 border-b py-4 pr-4 pl-4"
  >
    <MemberChip {member}></MemberChip>
    {#if user.id === member.id}
      <span class="text-primary">{member.email} ({m.you()})</span>
    {:else}
      <span class="text-primary">{member.email}</span>
    {/if}
    <div class="flex-grow"></div>
    {#if $currentSpace.hasPermission("edit", "member") && user.id !== member.id}
      <SpaceMemberRole kind="user" {member}></SpaceMemberRole>
    {:else}
      <span class="text-secondary px-2 capitalize">{member.role}</span>
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
                class="border-default hover:bg-hover-dimmer flex items-center justify-between gap-4 border-b py-4 pr-4 pl-4"
              >
                <div class="flex items-center gap-2">
                  <IconPeople class="text-secondary h-6 w-6" />
                  <span class="text-primary font-medium">{groupMember.name}</span>
                </div>
                <span class="text-secondary text-sm">
                  {groupMember.user_count}
                  {groupMember.user_count === 1 ? m.user() : m.users()}
                </span>
                <div class="flex-grow"></div>
                {#if $currentSpace.hasPermission("edit", "group_member")}
                  <SpaceMemberRole kind="group" member={groupMember}></SpaceMemberRole>
                {:else}
                  <span class="text-secondary px-2 capitalize">{groupMember.role}</span>
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
