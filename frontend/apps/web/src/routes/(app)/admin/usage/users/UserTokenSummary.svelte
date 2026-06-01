<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import {
    IntricError,
    type UserSortBy,
    type UserTokenUsage,
    type UserTokenUsageSummary
  } from "@intric/intric-js";
  import type { CostRateMap } from "$lib/features/ai-models/costRates";
  import UserOverviewBar from "./UserOverviewBar.svelte";
  import UserTokenTable from "./UserTokenTable.svelte";
  import { CalendarDate, type DateValue } from "@internationalized/date";
  import { getIntric } from "$lib/core/Intric";
  import { Input } from "@intric/ui";
  import { goto } from "$app/navigation";
  import { page } from "$app/stores";
  import { m } from "$lib/paraglide/messages";
  import { SvelteURLSearchParams } from "svelte/reactivity";

  type Props = { costRates: CostRateMap };
  const { costRates }: Props = $props();

  let userStats = $state<UserTokenUsageSummary | null>(null);
  let isLoading = $state(false);
  let error = $state<string | null>(null);
  let fetchId = 0;

  // Reactive pagination state derived from URL search parameters
  const paginationState = $derived.by(() => {
    const searchParams = $page.url.searchParams;
    return {
      page: parseInt(searchParams.get("page") || "1"),
      perPage: 25, // Fixed value
      sortBy: (searchParams.get("sortBy") as UserSortBy) || "total_tokens",
      sortOrder: (searchParams.get("sortOrder") as "asc" | "desc") || "desc"
    };
  });

  const intric = getIntric();

  const now = new Date();
  const today = new CalendarDate(now.getFullYear(), now.getMonth() + 1, now.getDate());
  const BASE_DAYS = 30;
  const BASE_HIGH_THRESHOLD = 500_000;
  const BASE_MEDIUM_THRESHOLD = 50_000;

  let dateRange = $state({
    start: today.subtract({ days: 30 }),
    end: today
  });

  // Scale thresholds proportionally to the selected date range
  const thresholds = $derived.by(() => {
    if (!dateRange.start || !dateRange.end) {
      return { high: BASE_HIGH_THRESHOLD, medium: BASE_MEDIUM_THRESHOLD };
    }
    const startMs = new Date(dateRange.start.toString()).getTime();
    const endMs = new Date(dateRange.end.toString()).getTime();
    const days = Math.max(1, Math.round((endMs - startMs) / (1000 * 60 * 60 * 24)));
    const scale = days / BASE_DAYS;
    return {
      high: Math.round(BASE_HIGH_THRESHOLD * scale),
      medium: Math.round(BASE_MEDIUM_THRESHOLD * scale)
    };
  });

  async function updateUserStats(
    timeframe: { start: CalendarDate; end: CalendarDate },
    page: number,
    perPage: number,
    sortBy: UserSortBy,
    sortOrder: string
  ) {
    const id = ++fetchId;
    isLoading = true;
    error = null;
    try {
      const result = await intric.usage.tokens.getUsersSummary({
        startDate: timeframe.start.toString(),
        // We add one day so the end day includes the whole day. otherwise this would be interpreted as 00:00
        endDate: timeframe.end.add({ days: 1 }).toString(),
        page: page,
        perPage: perPage,
        sortBy: sortBy,
        sortOrder: sortOrder
      });
      if (id !== fetchId) return; // Stale response, discard
      userStats = result;
    } catch (err: unknown) {
      if (id !== fetchId) return;
      error = err instanceof IntricError ? err.message : "unknown error";
      console.error("Failed to load user token usage:", err);
    } finally {
      if (id === fetchId) {
        isLoading = false;
      }
    }
  }

  function handleDateChange(range: { start: DateValue; end: DateValue }) {
    dateRange = range as { start: CalendarDate; end: CalendarDate };
    // Reset to page 1 when date range changes to avoid empty pages
    const url = new URL($page.url);
    if (url.searchParams.has("page")) {
      url.searchParams.set("page", "1");
      // eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic URL built from current page
      goto(url, { replaceState: true });
    }
  }

  // Single effect handles all data fetching — triggered by dateRange or pagination changes
  $effect(() => {
    const { page, perPage, sortBy, sortOrder } = paginationState;
    if (dateRange.start && dateRange.end) {
      updateUserStats(dateRange, page, perPage, sortBy, sortOrder);
    }
  });

  function onUserClick(user: UserTokenUsage) {
    // Preserve current URL state by including pagination parameters
    const currentUrl = new URL($page.url);
    const params = new SvelteURLSearchParams();

    // Preserve pagination parameters for the back navigation
    if (currentUrl.searchParams.get("page"))
      params.set("page", currentUrl.searchParams.get("page")!);
    if (currentUrl.searchParams.get("sortBy"))
      params.set("sortBy", currentUrl.searchParams.get("sortBy")!);
    if (currentUrl.searchParams.get("sortOrder"))
      params.set("sortOrder", currentUrl.searchParams.get("sortOrder")!);

    const userDetailUrl = `/admin/usage/users/${user.user_id}${params.toString() ? "?" + params.toString() : ""}`;
    // eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic path with user id and query
    goto(userDetailUrl);
  }

  function onPageChange(newPage: number) {
    const url = new URL($page.url);
    url.searchParams.set("page", newPage.toString());
    // eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic URL built from current page
    goto(url, { replaceState: true });
  }

  function onSortChange(newSortBy: UserSortBy, newSortOrder: "asc" | "desc") {
    const url = new URL($page.url);
    url.searchParams.set("sortBy", newSortBy);
    url.searchParams.set("sortOrder", newSortOrder);
    // Reset to page 1 when sorting changes
    url.searchParams.set("page", "1");
    // eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic URL built from current page
    goto(url, { replaceState: true });
  }
</script>

<Settings.Group title={m.usage_by_user()}>
  <Settings.Row title={m.usage_by_user_description()} description="" fullWidth>
    <div slot="toolbar" class="mb-4">
      <Input.DateRange bind:value={dateRange} onValueCommit={handleDateChange}></Input.DateRange>
    </div>

    {#if isLoading}
      <div class="flex justify-center p-8">
        <div class="text-gray-500">{m.loading_user_token_usage()}</div>
      </div>
    {:else if error}
      <div class="flex justify-center p-8">
        <div class="text-red-500">{error}</div>
      </div>
    {:else if userStats && userStats.users.length > 0}
      <UserOverviewBar
        {userStats}
        highThreshold={thresholds.high}
        mediumThreshold={thresholds.medium}
      ></UserOverviewBar>
      <div class="mt-4">
        <UserTokenTable
          users={userStats.users}
          totalUsers={userStats.total_users}
          page={paginationState.page}
          perPage={paginationState.perPage}
          sortBy={paginationState.sortBy}
          sortOrder={paginationState.sortOrder}
          highThreshold={thresholds.high}
          mediumThreshold={thresholds.medium}
          {costRates}
          {onUserClick}
          {onPageChange}
          {onSortChange}
        />
      </div>
    {:else}
      <div class="flex justify-center p-8">
        <div class="text-gray-500">{m.no_user_token_usage_data()}</div>
      </div>
    {/if}
  </Settings.Row>
</Settings.Group>
