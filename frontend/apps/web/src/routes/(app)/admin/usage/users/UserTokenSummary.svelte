<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { IntricError, type UserSortBy, type UserTokenUsage, type UserTokenUsageSummary } from "@intric/intric-js";
  import UserOverviewBar from "./UserOverviewBar.svelte";
  import UserTokenTable from "./UserTokenTable.svelte";
  import { CalendarDate } from "@internationalized/date";
  import { getIntric } from "$lib/core/Intric";
  import { Input } from "@intric/ui";
  import { goto } from "$app/navigation";

  let userStats = $state<UserTokenUsageSummary | null>(null);
  let isLoading = $state(false);
  let error = $state<string | null>(null);
  let page = $state(1);
  let perPage = $state(25); // Fixed value, no dropdown
  let sortBy = $state<UserSortBy>("total_tokens");
  let sortOrder = $state<"asc" | "desc">("desc");


  const intric = getIntric();

  const now = new Date();
  const today = new CalendarDate(now.getFullYear(), now.getMonth() + 1, now.getUTCDate());
  let dateRange = $state({
    start: today.subtract({ days: 30 }),
    end: today
  });

  async function updateUserStats(timeframe: { start: CalendarDate; end: CalendarDate }, page: number, perPage: number, sortBy: UserSortBy, sortOrder: string) {
    isLoading = true;
    error = null;
    try {
      userStats = await intric.usage.tokens.getUsersSummary({
        startDate: timeframe.start.toString(),
        // We add one day so the end day includes the whole day. otherwise this would be interpreted as 00:00
        endDate: timeframe.end.add({ days: 1 }).toString(),
        page: page,
        perPage: perPage,
        sortBy: sortBy,
        sortOrder: sortOrder
      });
    } catch (err: unknown) {
      error = err instanceof IntricError ? err.message : "unknown error";
      console.error('Failed to load user token usage:', err);
    } finally {
      isLoading = false;
    }
  }

  $effect(() => {
    if (dateRange.start && dateRange.end) {
      updateUserStats(dateRange, page, perPage, sortBy, sortOrder);
    }
  });

  function onUserClick(user: UserTokenUsage) {
    goto(`/admin/usage/users/${user.user_id}`);
  }

  function onPageChange(newPage: number) {
    page = newPage;
  }

  function onSortChange(newSortBy: UserSortBy, newSortOrder: "asc" | "desc") {
    sortBy = newSortBy;
    sortOrder = newSortOrder;
  }


</script>

<Settings.Page>
  <Settings.Group title="Overview">
    {#if userStats}
      <UserOverviewBar {userStats}></UserOverviewBar>
    {/if}
  </Settings.Group>
  <Settings.Group title="Details">
    <Settings.Row
      title="Usage by user"
      description="See token usage broken down by individual users within your organization."
      fullWidth
    >
      <div slot="toolbar" class="mb-4">
        <Input.DateRange bind:value={dateRange}></Input.DateRange>
      </div>

      {#if isLoading}
        <div class="flex justify-center p-8">
          <div class="text-gray-500">Loading user token usage...</div>
        </div>
      {:else if error}
        <div class="flex justify-center p-8">
          <div class="text-red-500">{error}</div>
        </div>
      {:else if userStats}
        <div class="space-y-4">
          <UserTokenTable users={userStats.users} totalUsers={userStats.total_users} {page} {perPage} {sortBy} {sortOrder} {onUserClick} {onPageChange} {onSortChange}></UserTokenTable>
        </div>
      {:else}
        <div class="flex justify-center p-8">
          <div class="text-gray-500">No user token usage data available for this period.</div>
        </div>
      {/if}
    </Settings.Row>
  </Settings.Group>
</Settings.Page>
