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
  import { page } from "$app/stores";

  let userStats = $state<UserTokenUsageSummary | null>(null);
  let isLoading = $state(false);
  let error = $state<string | null>(null);

  // Reactive pagination state derived from URL search parameters
  const paginationState = $derived.by(() => {
    const searchParams = $page.url.searchParams;
    return {
      page: parseInt(searchParams.get('page') || '1'),
      perPage: 25, // Fixed value
      sortBy: (searchParams.get('sortBy') as UserSortBy) || "total_tokens",
      sortOrder: (searchParams.get('sortOrder') as "asc" | "desc") || "desc"
    };
  });


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
      updateUserStats(dateRange, paginationState.page, paginationState.perPage, paginationState.sortBy, paginationState.sortOrder);
    }
  });

    function onUserClick(user: UserTokenUsage) {
    // Preserve current URL state by including pagination parameters
    const currentUrl = new URL($page.url);
    const params = new URLSearchParams();

    // Preserve pagination parameters for the back navigation
    if (currentUrl.searchParams.get('page')) params.set('page', currentUrl.searchParams.get('page')!);
    if (currentUrl.searchParams.get('sortBy')) params.set('sortBy', currentUrl.searchParams.get('sortBy')!);
    if (currentUrl.searchParams.get('sortOrder')) params.set('sortOrder', currentUrl.searchParams.get('sortOrder')!);

    const userDetailUrl = `/admin/usage/users/${user.user_id}${params.toString() ? '?' + params.toString() : ''}`;
    goto(userDetailUrl);
  }

  function onPageChange(newPage: number) {
    const url = new URL($page.url);
    url.searchParams.set('page', newPage.toString());
    goto(url, { replaceState: true });
  }

  function onSortChange(newSortBy: UserSortBy, newSortOrder: "asc" | "desc") {
    const url = new URL($page.url);
    url.searchParams.set('sortBy', newSortBy);
    url.searchParams.set('sortOrder', newSortOrder);
    // Reset to page 1 when sorting changes
    url.searchParams.set('page', '1');
    goto(url, { replaceState: true });
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
          <UserTokenTable
            users={userStats.users}
            totalUsers={userStats.total_users}
            page={paginationState.page}
            perPage={paginationState.perPage}
            sortBy={paginationState.sortBy}
            sortOrder={paginationState.sortOrder}
            {onUserClick}
            {onPageChange}
            {onSortChange}
          />
        </div>
      {:else}
        <div class="flex justify-center p-8">
          <div class="text-gray-500">No user token usage data available for this period.</div>
        </div>
      {/if}
    </Settings.Row>
  </Settings.Group>
</Settings.Page>
