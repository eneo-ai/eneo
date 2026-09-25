<!--
  The administrator's own relation to the space, first on the page: viewing
  it without content, a member, or a member through a group. Its heading is
  where focus lands after joining or leaving, when the buttons have changed.
-->
<script lang="ts">
  import type { AdminSpaceDetail } from "@eneo/eneo-js";
  import { Eye, UserCheck, UsersRound } from "@lucide/svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { formatDateMedium } from "$lib/core/formatting/dateTime";
  import { formatList } from "$lib/core/formatting/formatList";
  import JoinSpaceDialog from "$lib/features/spaces/oversight/JoinSpaceDialog.svelte";
  import { spaceRoleLabel } from "$lib/features/spaces/roles";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import LeaveSpaceDialog from "./LeaveSpaceDialog.svelte";

  type Props = { space: AdminSpaceDetail };

  let { space }: Props = $props();

  let heading = $state<HTMLHeadingElement | null>(null);

  const membership = $derived(space.members.viewer_membership);
  const variant = $derived(
    membership.direct_role ? "member" : membership.role ? "group" : "viewing"
  );
  const groups = $derived(formatList(membership.via_groups.map((group) => group.name)));
</script>

{#snippet openSpace()}
  <!-- eslint-disable svelte/no-navigation-without-resolve -- localized href built from a typed id -->
  <Button href={localizeHref(`/spaces/${space.id}/overview`)} class="max-md:min-h-12">
    {m.admin_spaces_open_space()}
  </Button>
  <!-- eslint-enable svelte/no-navigation-without-resolve -->
{/snippet}

<section
  aria-labelledby="space-membership-title"
  class="border-default bg-secondary flex flex-col gap-4 rounded-lg border p-4 @3xl:flex-row @3xl:items-center"
>
  <div class="flex min-w-0 flex-1 gap-3">
    {#if variant === "viewing"}
      <Eye class="text-secondary mt-0.5 size-5 shrink-0" aria-hidden="true" />
    {:else if variant === "member"}
      <UserCheck class="text-secondary mt-0.5 size-5 shrink-0" aria-hidden="true" />
    {:else}
      <UsersRound class="text-secondary mt-0.5 size-5 shrink-0" aria-hidden="true" />
    {/if}
    <div class="flex min-w-0 flex-col gap-1">
      <h2
        id="space-membership-title"
        bind:this={heading}
        tabindex="-1"
        class="text-base font-semibold outline-none"
      >
        {#if variant === "viewing"}
          {m.admin_spaces_banner_viewing_title()}
        {:else if variant === "member"}
          {m.admin_spaces_banner_member_title()}
        {:else}
          {m.admin_spaces_banner_group_title()}
        {/if}
      </h2>
      {#if variant === "viewing"}
        <p class="max-w-[75ch] text-sm">{m.admin_spaces_banner_viewing_body()}</p>
      {:else if variant === "member" && membership.role}
        <p class="text-sm">
          {m.admin_spaces_banner_your_role({ role: spaceRoleLabel(membership.role) })}
          {#if membership.oversight_joined_at}
            {m.admin_spaces_banner_joined({
              date: formatDateMedium(membership.oversight_joined_at)
            })}
          {/if}
        </p>
        {#if !membership.can_leave}
          <p id="space-leave-blocked" class="text-secondary text-sm">
            {m.admin_spaces_leave_last_admin()}
          </p>
        {/if}
      {:else if membership.role}
        <p class="text-sm">
          {m.admin_spaces_banner_group_role({ role: spaceRoleLabel(membership.role), groups })}
          {#if membership.joinable_roles.length > 0}
            {m.admin_spaces_banner_group_join_hint()}
          {/if}
        </p>
      {/if}
    </div>
  </div>

  <div class="flex flex-wrap items-center gap-2 @max-3xl:pl-8">
    {#if variant === "member"}
      {@render openSpace()}
      <LeaveSpaceDialog
        {space}
        {membership}
        disabledReasonId="space-leave-blocked"
        focusAfterLeave={() => heading}
      />
    {:else}
      {#if variant === "group"}
        {@render openSpace()}
      {/if}
      <JoinSpaceDialog
        {space}
        {membership}
        triggerVariant={variant === "group" ? "outline" : "default"}
        focusAfterJoin={() => heading}
      />
    {/if}
  </div>
</section>
