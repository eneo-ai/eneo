<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { getAppContext } from "$lib/core/AppContext";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import MemberChip from "$lib/features/spaces/components/MemberChip.svelte";
  import AddMember from "./AddMember.svelte";
  import AddGroupMember from "./AddGroupMember.svelte";
  import MemberRole from "./MemberRole.svelte";
  import GroupMemberRole from "./GroupMemberRole.svelte";
  import { Page, Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import { IconGroup } from "@intric/icons/group";

  const { user } = getAppContext();

  const {
    state: { currentSpace }
  } = getSpacesManager();

  const isViewerRoleAvailable = $currentSpace.available_roles.some(
    (role) => role.value === "viewer"
  );

  $: editors = $currentSpace.members.filter(
    (member) => member.role === "admin" || member.role === "editor"
  );

  $: viewers = $currentSpace.members.filter((member) => member.role === "viewer");

  $: groupMembers = $currentSpace.group_members?.items ?? [];
  $: hasGroupMemberPermission = $currentSpace.hasPermission("add", "group_member");
</script>

<svelte:head>
  <title>{m.app_name()} – {$currentSpace.name} – {m.members()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.members()}></Page.Title>
    <Page.Flex>
      {#if hasGroupMemberPermission}
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
                  <MemberRole {member}></MemberRole>
                {:else}
                  <span class="text-secondary px-2 capitalize">{member.role}</span>
                {/if}
              </div>
            {/each}
          </div>
        </Settings.Row>

        {#if isViewerRoleAvailable}
          <Settings.Row title={m.viewers()} description={m.viewers_description()}>
            <div class="flex flex-grow flex-col">
              {#if viewers.length > 0}
                {#each viewers as member (member.id)}
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
                      <MemberRole {member}></MemberRole>
                    {:else}
                      <span class="text-secondary px-2 capitalize">{member.role}</span>
                    {/if}
                  </div>
                {/each}
              {:else}
                <div
                  class="border-default text-muted hover:bg-hover-dimmer flex items-center justify-between gap-4 border-b py-4 pr-4 pl-4"
                >
                  {m.no_viewers_in_space()}
                </div>
              {/if}
            </div>
          </Settings.Row>
        {/if}
      </Settings.Group>

      <Settings.Group title={m.group_members()}>
        <Settings.Row title={m.user_groups()} description={m.user_groups_description()}>
          <div class="flex flex-grow flex-col">
            {#if groupMembers.length > 0}
              {#each groupMembers as groupMember (groupMember.id)}
                <div
                  class="border-default hover:bg-hover-dimmer flex items-center justify-between gap-4 border-b py-4 pr-4 pl-4"
                >
                  <div class="flex items-center gap-2">
                    <IconGroup class="h-6 w-6 text-secondary" />
                    <span class="text-primary font-medium">{groupMember.name}</span>
                  </div>
                  <span class="text-secondary text-sm">
                    {groupMember.user_count} {groupMember.user_count === 1 ? m.user() : m.users()}
                  </span>
                  <div class="flex-grow"></div>
                  {#if $currentSpace.hasPermission("edit", "group_member")}
                    <GroupMemberRole {groupMember}></GroupMemberRole>
                  {:else}
                    <span class="text-secondary px-2 capitalize">{groupMember.role}</span>
                  {/if}
                </div>
              {/each}
            {:else}
              <div
                class="border-default text-muted hover:bg-hover-dimmer flex items-center justify-between gap-4 border-b py-4 pr-4 pl-4"
              >
                {m.no_group_members_in_space()}
              </div>
            {/if}
          </div>
        </Settings.Row>
      </Settings.Group>
    </Settings.Page>
  </Page.Main>
</Page.Root>
