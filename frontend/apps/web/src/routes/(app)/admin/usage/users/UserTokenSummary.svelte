<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import {
    EneoError,
    type UserSortBy,
    type UserTokenUsage,
    type UserTokenUsageSummary
  } from "@eneo/eneo-js";
  import type { CostRateMap } from "$lib/features/ai-models/costRates";
  import UserOverviewBar from "./UserOverviewBar.svelte";
  import UserTokenTable from "./UserTokenTable.svelte";
  import { CalendarDate, type DateValue } from "@internationalized/date";
  import { getEneo } from "$lib/core/Eneo";
  import DateRangePicker from "$lib/components/DateRangePicker.svelte";
  import { goto } from "$app/navigation";
  import { page } from "$app/stores";
  import { m } from "$lib/paraglide/messages";
  import { resolve } from "$app/paths";
  import { Button } from "$lib/components/ui/button";
  import { Input as SearchInput } from "$lib/components/ui/input";
  import { readUserUsageQuery, userUsageUrl } from "./usage-query";

  type Props = { costRates: CostRateMap };
  const { costRates }: Props = $props();

  let userStats = $state<UserTokenUsageSummary | null>(null);
  let isLoading = $state(false);
  let error = $state<string | null>(null);
  let fetchId = 0;

  const paginationState = $derived(readUserUsageQuery($page.url));
  let searchDraft = $derived(paginationState.search);

  const eneo = getEneo();

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
    sortOrder: "asc" | "desc",
    search: string
  ) {
    const id = ++fetchId;
    isLoading = true;
    error = null;
    try {
      const result = await eneo.usage.tokens.getUsersSummary({
        startDate: timeframe.start.toString(),
        // We add one day so the end day includes the whole day. otherwise this would be interpreted as 00:00
        endDate: timeframe.end.add({ days: 1 }).toString(),
        page: page,
        perPage: perPage,
        sortBy: sortBy,
        sortOrder: sortOrder,
        search: search || undefined
      });
      if (id !== fetchId) return; // Stale response, discard
      userStats = result;
    } catch (err: unknown) {
      if (id !== fetchId) return;
      error = err instanceof EneoError ? err.message : "unknown error";
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
    const { page, perPage, sortBy, sortOrder, search } = paginationState;
    if (dateRange.start && dateRange.end) {
      updateUserStats(dateRange, page, perPage, sortBy, sortOrder, search);
    }
  });

  function onUserClick(user: UserTokenUsage) {
    const query = $page.url.search;
    goto(resolve(`/admin/usage/users/${user.user_id}${query}`));
  }

  function navigate(change: Parameters<typeof userUsageUrl>[1]) {
    // eslint-disable-next-line svelte/no-navigation-without-resolve -- same-route URL retaining current filters
    goto(userUsageUrl($page.url, change), { noScroll: true, keepFocus: true });
  }

  function onPageChange(page: number) {
    navigate({ page });
  }
  function onSortChange(sortBy: UserSortBy, sortOrder: "asc" | "desc") {
    navigate({ sortBy, sortOrder });
  }
</script>

<Settings.Group title={m.usage_by_user()}>
  <Settings.Row title={m.usage_by_user_description()} description="" fullWidth>
    <div slot="toolbar" class="mb-4">
      <DateRangePicker bind:value={dateRange} onValueCommit={handleDateChange}></DateRangePicker>
    </div>

    <form
      class="mb-4 flex flex-wrap items-center gap-2"
      role="search"
      aria-label={m.usage_by_user()}
      onsubmit={(event) => {
        event.preventDefault();
        navigate({ search: searchDraft });
      }}
    >
      <SearchInput
        type="search"
        class="min-w-48 flex-1"
        bind:value={searchDraft}
        maxlength={200}
        placeholder={m.usage_user_search()}
        aria-label={m.usage_user_search()}
      />
      <Button type="submit">{m.search()}</Button>
      <Button
        variant="outline"
        onclick={() => {
          searchDraft = "";
          navigate({ search: "" });
        }}>{m.admin_users_clear_filters()}</Button
      >
    </form>

    {#if isLoading}
      <div class="flex justify-center p-8">
        <div class="text-muted-foreground">{m.loading_user_token_usage()}</div>
      </div>
    {:else if error}
      <div class="flex justify-center p-8">
        <div class="text-negative-stronger">{error}</div>
      </div>
    {:else if userStats && userStats.users.length > 0}
      <UserOverviewBar
        {userStats}
        highThreshold={thresholds.high}
        mediumThreshold={thresholds.medium}
      ></UserOverviewBar>
      <p class="text-muted-foreground mt-4 text-sm" role="status">
        {m.pagination_showing_range({
          start: (paginationState.page - 1) * paginationState.perPage + 1,
          end: Math.min(paginationState.page * paginationState.perPage, userStats.total_users),
          total: userStats.total_users
        })}
      </p>
      <div class="mt-3">
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
        <div class="text-muted-foreground">{m.no_user_token_usage_data()}</div>
      </div>
    {/if}
  </Settings.Row>
</Settings.Group>
