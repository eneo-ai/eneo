<!--
  Managing a space's members as an organisation administrator, without being
  a member. Changing one's own access goes through joining or leaving, which
  record a reason, so one's own row has no controls here.
-->
<script lang="ts">
  import {
    EneoError,
    type AdminSpaceGroupMember,
    type AdminSpaceMembers,
    type AdminSpaceUserMember,
    type SpaceRoleValue,
    type UserGroup,
    type UserSparse
  } from "@eneo/eneo-js";
  import { Info } from "@lucide/svelte";
  import { tick } from "svelte";
  import { invalidate } from "$app/navigation";
  import { toast } from "$lib/components/toast";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Command from "$lib/components/ui/command/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import { getErrorMessage } from "$lib/core/errors";
  import { formatDateMedium, intlLocale } from "$lib/core/formatting/dateTime";
  import AddSpaceMemberDialog from "$lib/features/spaces/components/AddSpaceMemberDialog.svelte";
  import SpaceMemberRole from "$lib/features/spaces/components/SpaceMemberRole.svelte";
  import { SPACE_ROLES, spaceRoleLabel } from "$lib/features/spaces/roles";
  import { UserList } from "$lib/features/users/user-list.svelte";
  import { m } from "$lib/paraglide/messages";
  import { groupCount, peopleCount } from "../labels";

  type Props = {
    space: { id: string; name: string; members: AdminSpaceMembers };
    currentUserId: string;
  };

  let { space, currentUserId }: Props = $props();

  const eneo = getEneo();
  const uid = $props.id();
  const number = new Intl.NumberFormat(intlLocale());
  const format = (value: number) => number.format(value);

  // A change's response shows at once; the page's data takes over again when it reloads.
  let members = $derived(space.members);
  let announcement = $state("");
  let peopleHeading = $state<HTMLHeadingElement | null>(null);
  let groupsHeading = $state<HTMLHeadingElement | null>(null);

  // With a single manageable administrator left, demoting or removing it is refused.
  const onlyAdmin = $derived(
    members.admins.principals.length === 1 ? members.admins.principals[0] : null
  );
  const isOnlyAdmin = (kind: "user" | "group", id: string) =>
    onlyAdmin?.kind === kind && onlyAdmin.id === id;

  const personName = (user: Pick<AdminSpaceUserMember, "username" | "email">) =>
    user.username || user.email;

  const summary = $derived(
    m.admin_spaces_members_summary({
      people: peopleCount(members.users.length, format),
      groups: groupCount(members.groups.length, format),
      total:
        members.member_count === 1
          ? m.admin_spaces_count_members_one()
          : m.admin_spaces_count_members({ count: format(members.member_count) })
    })
  );

  function saved(response: AdminSpaceMembers, message: string) {
    members = response;
    announcement = message;
    void invalidate("admin:space");
  }

  /** Someone else changed the members first: say so and show the current list. */
  function listChanged() {
    toast.info(m.admin_spaces_members_changed());
    announcement = m.admin_spaces_members_changed();
    return invalidate("admin:space");
  }

  const isGone = (error: unknown) => error instanceof EneoError && error.status === 404;

  function removeGroupBody(group: AdminSpaceGroupMember) {
    return group.user_count === 1
      ? m.admin_spaces_remove_body_group_one()
      : m.admin_spaces_remove_body_group({ count: format(group.user_count) });
  }

  async function changeRole(
    kind: "user" | "group",
    id: string,
    name: string,
    role: SpaceRoleValue
  ) {
    let response: AdminSpaceMembers;
    try {
      response =
        kind === "user"
          ? await eneo.spaces.admin.members.update({ spaceId: space.id, userId: id, role })
          : await eneo.spaces.admin.groupMembers.update({ spaceId: space.id, groupId: id, role });
    } catch (error) {
      if (isGone(error)) void listChanged();
      else toast.error(getErrorMessage(error));
      throw error;
    }
    const message = m.admin_spaces_role_changed({ name, role: spaceRoleLabel(role) });
    toast.success(message);
    saved(response, message);
  }

  async function remove(kind: "user" | "group", id: string, name: string) {
    try {
      const response =
        kind === "user"
          ? await eneo.spaces.admin.members.remove({ spaceId: space.id, userId: id })
          : await eneo.spaces.admin.groupMembers.remove({ spaceId: space.id, groupId: id });
      saved(response, m.admin_spaces_member_removed({ name }));
    } catch (error) {
      // Any other refusal, such as the last administrator, shows in the confirmation.
      if (!isGone(error)) throw error;
      await listChanged();
    }
    // The row and the button that opened the confirmation are gone.
    await tick();
    (kind === "user" ? peopleHeading : groupsHeading)?.focus();
  }

  // --- adding ------------------------------------------------------------------
  const userList = new UserList({ eneo });
  let personFilter = $state("");
  $effect(() => {
    userList.setFilter(personFilter);
  });
  // Oneself is listed but cannot be picked: joining records a reason, adding would not.
  const takenPeople = $derived([...members.users.map((user) => user.id), currentUserId]);

  let groupDialogOpen = $state(false);
  let groupFilter = $state("");
  let userGroups = $state<UserGroup[]>([]);
  const filteredGroups = $derived(
    userGroups.filter((group) => group.name.toLowerCase().includes(groupFilter.toLowerCase()))
  );
  $effect(() => {
    if (groupDialogOpen) void loadGroups();
  });

  async function loadGroups() {
    try {
      userGroups = await eneo.userGroups.list();
    } catch (error) {
      console.error("Failed to load user groups", error);
      userGroups = [];
    }
  }

  async function addPerson(user: UserSparse, role: SpaceRoleValue) {
    const response = await eneo.spaces.admin.members.add({
      spaceId: space.id,
      userId: user.id,
      role
    });
    const message = m.admin_spaces_member_added({
      name: user.username || user.email,
      role: spaceRoleLabel(role)
    });
    toast.success(message);
    saved(response, message);
  }

  async function addGroup(group: UserGroup, role: SpaceRoleValue) {
    const response = await eneo.spaces.admin.groupMembers.add({
      spaceId: space.id,
      groupId: group.id,
      role
    });
    const message = m.admin_spaces_member_added({ name: group.name, role: spaceRoleLabel(role) });
    toast.success(message);
    saved(response, message);
  }
</script>

{#snippet personOption(user: UserSparse, taken: boolean)}
  <div class="flex min-w-0 flex-col">
    <span class="truncate">{user.email}</span>
    {#if user.id === currentUserId}
      <span class="text-secondary text-xs">{m.admin_spaces_self_in_picker()}</span>
    {:else if taken}
      <span class="text-secondary text-xs">{m.admin_spaces_already_member()}</span>
    {/if}
  </div>
{/snippet}

{#snippet groupOption(group: UserGroup, taken: boolean)}
  <div class="flex min-w-0 flex-col">
    <span class="truncate">{group.name}</span>
    {#if taken}
      <span class="text-secondary text-xs">{m.admin_spaces_already_member()}</span>
    {/if}
  </div>
{/snippet}

{#snippet onlyAdminNote(id: string)}
  <p {id} class="text-secondary flex items-start gap-1.5 text-sm">
    <Info class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
    {m.admin_spaces_only_admin()}
  </p>
{/snippet}

<section aria-labelledby="space-members-title" class="flex flex-col gap-6">
  <div class="flex flex-col gap-4 @3xl:flex-row @3xl:items-start @3xl:justify-between">
    <div class="flex flex-col gap-1">
      <h2 id="space-members-title" tabindex="-1" class="text-lg font-semibold outline-none">
        {m.members()}
      </h2>
      <p class="text-secondary text-sm">{summary}</p>
    </div>
    <div class="flex flex-wrap gap-2">
      <AddSpaceMemberDialog
        bind:filter={personFilter}
        triggerLabel={m.admin_spaces_add_person()}
        triggerVariant="outline"
        title={m.admin_spaces_add_person_title({ space: space.name })}
        fieldLabel={m.admin_spaces_person()}
        searchPlaceholder={m.find_user()}
        submitLabel={m.add()}
        errorContext={m.admin_spaces_add_person_failed()}
        emptyMessage={m.no_matching_users_found()}
        items={userList.filteredUsers}
        addedIds={takenPeople}
        roles={SPACE_ROLES}
        getLabel={(user) => user.email}
        onAdd={addPerson}
        row={personOption}
      >
        {#snippet listEnd()}
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
        {/snippet}
      </AddSpaceMemberDialog>
      <AddSpaceMemberDialog
        bind:open={groupDialogOpen}
        bind:filter={groupFilter}
        triggerLabel={m.admin_spaces_add_group()}
        triggerVariant="outline"
        title={m.admin_spaces_add_group_title({ space: space.name })}
        fieldLabel={m.user_group()}
        searchPlaceholder={m.find_group()}
        submitLabel={m.add()}
        errorContext={m.admin_spaces_add_group_failed()}
        emptyMessage={userGroups.length === 0
          ? m.no_user_groups_found()
          : m.no_matching_groups_found()}
        items={filteredGroups}
        addedIds={members.groups.map((group) => group.id)}
        roles={SPACE_ROLES}
        getLabel={(group) => group.name}
        onAdd={addGroup}
        row={groupOption}
      />
    </div>
  </div>

  <p class="text-secondary flex max-w-[75ch] items-start gap-2 text-sm">
    <Info class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
    {m.admin_spaces_members_note()}
  </p>

  <p role="status" class="sr-only">{announcement}</p>

  <section aria-labelledby={`${uid}-people`} class="flex flex-col gap-3">
    <h3
      id={`${uid}-people`}
      bind:this={peopleHeading}
      tabindex="-1"
      class="text-base font-semibold outline-none"
    >
      {m.admin_spaces_people()}
    </h3>
    {#if members.users.length > 0}
      <ul
        aria-labelledby={`${uid}-people`}
        class="border-default bg-primary divide-default divide-y rounded-lg border"
      >
        {#each members.users as user (user.id)}
          {@const self = user.id === currentUserId}
          {@const only = isOnlyAdmin("user", user.id)}
          {@const name = personName(user)}
          <li class="flex flex-col gap-3 p-4 @2xl:flex-row @2xl:items-start">
            <div class="flex min-w-0 flex-1 flex-col gap-1">
              <p class="font-medium wrap-anywhere">
                {name}
                {#if self}<span class="text-secondary font-normal">({m.you()})</span>{/if}
              </p>
              {#if user.username}
                <p class="text-secondary text-sm wrap-anywhere">{user.email}</p>
              {/if}
              {#if user.is_tenant_admin || user.oversight_join || user.state !== "active"}
                <div class="flex flex-wrap gap-1.5 pt-1">
                  {#if user.is_tenant_admin}
                    <Badge variant="outline">{m.admin_spaces_badge_tenant_admin()}</Badge>
                  {/if}
                  {#if user.oversight_join}
                    <Badge variant="outline" class="h-auto whitespace-normal">
                      {m.space_oversight_member_badge({
                        date: formatDateMedium(user.oversight_join.joined_at)
                      })}
                    </Badge>
                  {/if}
                  {#if user.state === "inactive"}
                    <Badge variant="outline">{m.admin_spaces_badge_inactive()}</Badge>
                  {:else if user.state === "invited"}
                    <Badge variant="outline">{m.admin_spaces_badge_invited()}</Badge>
                  {/if}
                </div>
              {/if}
              {#if user.oversight_join}
                <p class="text-secondary text-sm wrap-anywhere">
                  {m.space_oversight_notice_reason({ reason: user.oversight_join.reason })}
                </p>
              {/if}
              {#if self}
                <p class="text-secondary text-sm">{m.admin_spaces_own_row_note()}</p>
              {:else if only}
                {@render onlyAdminNote(`${uid}-only-user-${user.id}`)}
              {/if}
            </div>
            {#if self}
              <p class="text-sm @2xl:pt-1.5">{spaceRoleLabel(user.role)}</p>
            {:else}
              <SpaceMemberRole
                class="@2xl:shrink-0"
                {name}
                role={user.role}
                roles={SPACE_ROLES}
                disabled={only}
                disabledReasonId={only ? `${uid}-only-user-${user.id}` : undefined}
                onChangeRole={(role) => changeRole("user", user.id, name, role)}
                onRemove={() => remove("user", user.id, name)}
                removeTitle={m.admin_spaces_remove_title({ name, space: space.name })}
                removeDescription={m.admin_spaces_remove_body_person({ name })}
              />
            {/if}
          </li>
        {/each}
      </ul>
    {:else}
      <p class="text-secondary text-sm">{m.admin_spaces_no_people()}</p>
    {/if}
  </section>

  <section aria-labelledby={`${uid}-groups`} class="flex flex-col gap-3">
    <h3
      id={`${uid}-groups`}
      bind:this={groupsHeading}
      tabindex="-1"
      class="text-base font-semibold outline-none"
    >
      {m.admin_spaces_groups()}
    </h3>
    {#if members.groups.length > 0}
      <ul
        aria-labelledby={`${uid}-groups`}
        class="border-default bg-primary divide-default divide-y rounded-lg border"
      >
        {#each members.groups as group (group.id)}
          {@const only = isOnlyAdmin("group", group.id)}
          <li class="flex flex-col gap-3 p-4 @2xl:flex-row @2xl:items-start">
            <div class="flex min-w-0 flex-1 flex-col gap-1">
              <p class="font-medium wrap-anywhere">{group.name}</p>
              <p class="text-secondary text-sm">{peopleCount(group.user_count, format)}</p>
              {#if only}
                {@render onlyAdminNote(`${uid}-only-group-${group.id}`)}
              {/if}
            </div>
            <SpaceMemberRole
              class="@2xl:shrink-0"
              name={group.name}
              role={group.role}
              roles={SPACE_ROLES}
              disabled={only}
              disabledReasonId={only ? `${uid}-only-group-${group.id}` : undefined}
              onChangeRole={(role) => changeRole("group", group.id, group.name, role)}
              onRemove={() => remove("group", group.id, group.name)}
              removeTitle={m.admin_spaces_remove_title({ name: group.name, space: space.name })}
              removeDescription={removeGroupBody(group)}
            />
          </li>
        {/each}
      </ul>
    {:else}
      <p class="text-secondary text-sm">{m.admin_spaces_no_groups()}</p>
    {/if}
  </section>
</section>
