<script lang="ts">
  import { onMount } from "svelte";
  import dayjs from "dayjs";
  import type { AdminCrawlerOverview, AdminCrawlerQuery } from "@eneo/eneo-js";
  import { ArrowRight, RefreshCw } from "lucide-svelte";
  import { Page } from "$lib/components/layout";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import * as Tabs from "$lib/components/ui/tabs/index.js";
  import CrawlRunCounts from "$lib/features/knowledge/CrawlRunCounts.svelte";
  import CrawlRunStatus from "$lib/features/knowledge/CrawlRunStatus.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import AdminCrawlDetails from "./AdminCrawlDetails.svelte";
  import CrawlLoadError from "$lib/features/knowledge/CrawlLoadError.svelte";
  import {
    crawlRunState,
    crawlRunStateLabel,
    type CrawlRunState
  } from "$lib/features/knowledge/crawlRunState";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";

  const eneo = getEneo();
  type Status = "all" | "issues" | "completed" | "unsuccessful" | Exclude<CrawlRunState, "unknown">;
  type Period = NonNullable<AdminCrawlerQuery["period"]>;
  type Day = "today" | "yesterday";
  const days: Day[] = ["today", "yesterday"];
  const outcomes = [
    { count: "completed", status: "completed" },
    { count: "partial", status: "partial" },
    { count: "failed", status: "unsuccessful" }
  ] as const;
  const periods: Period[] = ["today", "yesterday", "last_24_hours"];
  const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  let period = $state<Period>("today");
  let view = $state<"active" | "recent">("active");
  let status = $state<Status>("all");
  let searchInput = $state("");
  let search = $state("");
  let cursors = $state<(string | null)[]>([null]);
  let overview = $state<AdminCrawlerOverview | null>(null);
  let loading = $state(false);
  let rowsStale = $state(true);
  let loadFailed = $state(false);
  let selectedRunId = $state<string | null>(null);
  let detailsOpen = $state(false);
  let mounted = false;
  let refreshPending = false;

  const statuses = $derived<Status[]>(
    view === "active"
      ? ["all", "queued", "running", "finalizing", "stopping"]
      : [
          "all",
          "issues",
          "completed",
          "succeeded",
          "unchanged",
          "empty",
          "partial",
          "unsuccessful",
          "cancelled",
          "interrupted"
        ]
  );

  function query(): AdminCrawlerQuery {
    return {
      view,
      period,
      time_zone: timeZone,
      status: status === "all" ? undefined : status,
      search,
      limit: 50,
      cursor: cursors.at(-1) ?? null
    };
  }

  async function refresh(queueIfBusy = false) {
    if (!mounted) return;
    if (loading) {
      refreshPending ||= queueIfBusy;
      return;
    }
    const request = query();
    const requestKey = JSON.stringify(request);
    loading = true;
    try {
      const result = await eneo.adminCrawler.overview(request);
      if (mounted && requestKey === JSON.stringify(query())) {
        const dayChanged = overview && overview.calendar.today.date !== result.calendar.today.date;
        if (dayChanged && view === "recent" && period !== "last_24_hours" && cursors.length > 1) {
          cursors = [null];
          rowsStale = true;
          refreshPending = true;
        } else {
          rowsStale = false;
        }
        overview = result;
        loadFailed = false;
      }
    } catch {
      if (mounted && requestKey === JSON.stringify(query())) loadFailed = true;
    } finally {
      loading = false;
      if (mounted && refreshPending) {
        refreshPending = false;
        void refresh();
      }
    }
  }

  function filterChanged() {
    cursors = [null];
    rowsStale = true;
    loadFailed = false;
    void refresh(true);
  }

  function changeView(value: string) {
    if (value !== "active" && value !== "recent") return;
    view = value;
    status = "all";
    filterChanged();
  }

  function showIssues() {
    view = "recent";
    status = "issues";
    period = "last_24_hours";
    search = "";
    searchInput = "";
    filterChanged();
  }

  function showDay(day: Day, outcome: Status) {
    view = "recent";
    period = day;
    status = outcome;
    search = "";
    searchInput = "";
    filterChanged();
  }

  function periodLabel(value: Period) {
    if (value === "today") return m.admin_crawler_today();
    if (value === "yesterday") return m.admin_crawler_yesterday();
    return m.admin_crawler_last_day();
  }

  function calendarDate(value: string) {
    return new Intl.DateTimeFormat(getLocale(), {
      day: "numeric",
      month: "long",
      timeZone: "UTC"
    }).format(new Date(`${value}T00:00:00Z`));
  }

  function clearFilters() {
    status = "all";
    search = "";
    searchInput = "";
    filterChanged();
  }

  function statusLabel(value: Status) {
    if (value === "all") return m.admin_crawler_all_statuses();
    if (value === "issues") return m.admin_crawler_issues();
    if (value === "completed") return m.admin_crawler_completed_clean();
    if (value === "partial") return m.admin_crawler_with_warnings();
    if (value === "unsuccessful") return m.admin_crawler_unsuccessful();
    return crawlRunStateLabel(value);
  }

  function elapsed(from: string, until: string) {
    const seconds = Math.max(0, Math.floor((Date.parse(until) - Date.parse(from)) / 1000));
    return m.admin_crawler_elapsed({ minutes: Math.floor(seconds / 60), seconds: seconds % 60 });
  }

  function date(value: string | null | undefined) {
    return value ? dayjs(value).format("YYYY-MM-DD HH:mm") : "—";
  }

  onMount(() => {
    mounted = true;
    void refresh();
    const updateVisible = () => {
      if (!document.hidden) void refresh();
    };
    const timer = setInterval(updateVisible, 10_000);
    document.addEventListener("visibilitychange", updateVisible);
    return () => {
      mounted = false;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", updateVisible);
    };
  });
</script>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.admin_crawler_title()} />
    <Button variant="outline" size="sm" disabled={loading} onclick={() => refresh()}>
      <RefreshCw data-icon="inline-start" />{m.refresh()}
    </Button>
  </Page.Header>
  <Page.Main>
    <div class="flex min-w-0 flex-col gap-6 py-6 pr-6">
      <p class="text-secondary max-w-3xl text-sm">{m.admin_crawler_description()}</p>
      <div class="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
        <p>
          {m.admin_crawler_ongoing()}
          <strong class="ml-2 tabular-nums">{overview?.summary.ongoing ?? "—"}</strong>
        </p>
        <p>
          {m.admin_crawler_queued()}
          <strong class="ml-2 tabular-nums">{overview?.summary.queued ?? "—"}</strong>
        </p>
        <Button
          variant="ghost"
          size="sm"
          class="h-auto min-h-9 justify-start whitespace-normal text-left sm:ml-auto"
          onclick={showIssues}
          aria-label={m.admin_crawler_show_issues()}
        >
          {m.admin_crawler_issues()} · {m.admin_crawler_last_day()}
          <span class="tabular-nums">{overview?.summary.issues ?? "—"}</span>
          <ArrowRight data-icon="inline-end" />
        </Button>
      </div>
      <section class="flex flex-col gap-3" aria-label={m.admin_crawler_completed_view()}>
        <div class="grid gap-4 lg:grid-cols-2">
          {#each days as day (day)}
            <Card.Root size="sm" role="group" aria-labelledby={`crawler-${day}`}>
              <Card.Header class="flex flex-row flex-wrap items-baseline justify-between gap-2">
                <Card.Title id={`crawler-${day}`}>{periodLabel(day)}</Card.Title>
                {#if overview}<Card.Description
                    >{calendarDate(overview.calendar[day].date)}</Card.Description
                  >{/if}
              </Card.Header>
              <Card.Content>
                <div class="grid grid-cols-3 gap-1 sm:gap-2">
                  {#each outcomes as outcome (outcome.status)}
                    <Button
                      variant="ghost"
                      class="aria-pressed:bg-muted h-auto min-h-20 min-w-0 flex-col items-start justify-start gap-1 px-1 py-2 text-left whitespace-normal sm:px-2"
                      disabled={!overview}
                      aria-label={m.admin_crawler_show_day_status({
                        status: statusLabel(outcome.status),
                        day: periodLabel(day)
                      })}
                      aria-pressed={view === "recent" &&
                        period === day &&
                        status === outcome.status}
                      onclick={() => showDay(day, outcome.status)}
                    >
                      {#if overview}<span class="text-xl font-semibold tabular-nums sm:text-2xl"
                          >{overview.calendar[day][outcome.count].toLocaleString(getLocale())}</span
                        >
                      {:else if loadFailed}<span class="text-2xl">—</span>
                      {:else}<Skeleton class="h-8 w-12" />{/if}
                      <span class="text-secondary text-xs leading-5"
                        >{statusLabel(outcome.status)}</span
                      >
                    </Button>
                  {/each}
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  class="text-secondary aria-pressed:bg-muted mt-2 max-w-full justify-start text-xs whitespace-normal"
                  disabled={!overview}
                  aria-label={m.admin_crawler_show_day_status({
                    status: statusLabel("cancelled"),
                    day: periodLabel(day)
                  })}
                  aria-pressed={view === "recent" && period === day && status === "cancelled"}
                  onclick={() => showDay(day, "cancelled")}
                  >{m.admin_crawler_cancelled_count({
                    count: overview
                      ? overview.calendar[day].cancelled.toLocaleString(getLocale())
                      : "—"
                  })}</Button
                >
              </Card.Content>
            </Card.Root>
          {/each}
        </div>
        <p class="text-secondary max-w-3xl text-xs leading-5">
          {m.admin_crawler_calendar_help({ timeZone: overview?.calendar.time_zone ?? timeZone })}
        </p>
      </section>

      <Tabs.Root value={view} onValueChange={changeView}>
        <Tabs.List aria-label={m.admin_crawler_title()}>
          <Tabs.Trigger value="active">{m.admin_crawler_active()}</Tabs.Trigger>
          <Tabs.Trigger value="recent">{m.admin_crawler_completed_view()}</Tabs.Trigger>
        </Tabs.List>
        {#key view}
          <Tabs.Content value={view}>
            <div class="flex flex-col gap-4 pt-3">
              <form
                class="flex flex-wrap items-end gap-3"
                onsubmit={(event) => {
                  event.preventDefault();
                  search = searchInput.trim();
                  filterChanged();
                }}
              >
                <Field.Field class="min-w-52 flex-1">
                  <Field.Label for="crawler-search">{m.admin_crawler_search()}</Field.Label>
                  <Input
                    id="crawler-search"
                    bind:value={searchInput}
                    maxlength={200}
                    placeholder={m.admin_crawler_search_hint()}
                  />
                </Field.Field>
                {#if view === "recent"}
                  <Field.Field class="w-full sm:w-44">
                    <Field.Label for="crawler-period">{m.admin_crawler_period()}</Field.Label>
                    <Select.Root
                      type="single"
                      value={period}
                      onValueChange={(value) => {
                        period = periods.find((option) => option === value) ?? "today";
                        filterChanged();
                      }}
                    >
                      <Select.Trigger id="crawler-period" class="w-full"
                        >{periodLabel(period)}</Select.Trigger
                      >
                      <Select.Content
                        ><Select.Group>
                          {#each periods as option (option)}<Select.Item value={option}
                              >{periodLabel(option)}</Select.Item
                            >{/each}
                        </Select.Group></Select.Content
                      >
                    </Select.Root>
                  </Field.Field>
                {/if}
                <Field.Field class="w-full sm:w-56">
                  <Field.Label for="crawler-status">{m.status()}</Field.Label>
                  <Select.Root
                    type="single"
                    value={status}
                    onValueChange={(value) => {
                      status = statuses.find((option) => option === value) ?? "all";
                      filterChanged();
                    }}
                  >
                    <Select.Trigger id="crawler-status" class="w-full"
                      >{statusLabel(status)}</Select.Trigger
                    >
                    <Select.Content
                      ><Select.Group>
                        {#each statuses as option (option)}<Select.Item value={option}
                            >{statusLabel(option)}</Select.Item
                          >{/each}
                      </Select.Group></Select.Content
                    >
                  </Select.Root>
                </Field.Field>
                <Button type="submit" variant="outline">{m.search()}</Button>
                {#if search || searchInput || status !== "all"}
                  <Button type="button" variant="ghost" onclick={clearFilters}
                    >{m.admin_crawler_clear_filters()}</Button
                  >
                {/if}
              </form>

              {#if loadFailed}
                <CrawlLoadError
                  message={overview && !rowsStale
                    ? m.admin_crawler_refresh_error()
                    : m.admin_crawler_error()}
                  {loading}
                  onretry={() => refresh()}
                />
              {/if}

              <div aria-busy={loading}>
                {#if rowsStale && !loadFailed}
                  <div class="flex flex-col gap-3" role="status" aria-label={m.loading()}>
                    {#each [1, 2, 3] as row (row)}<Skeleton class="h-16 w-full" />{/each}
                  </div>
                {:else if overview && !rowsStale}
                  <Table.Root class="min-w-[960px]">
                    <Table.Caption class="sr-only"
                      >{view === "active"
                        ? m.admin_crawler_active()
                        : m.admin_crawler_last_day()}</Table.Caption
                    >
                    <Table.Header
                      ><Table.Row>
                        <Table.Head>{m.website()}</Table.Head>
                        <Table.Head>{m.admin_crawler_space()}</Table.Head>
                        <Table.Head>{m.status()}</Table.Head>
                        <Table.Head>{m.admin_crawler_result()}</Table.Head>
                        <Table.Head>{m.admin_crawler_time()}</Table.Head>
                        <Table.Head>{m.admin_crawler_last_indexed()}</Table.Head>
                      </Table.Row></Table.Header
                    >
                    <Table.Body>
                      {#each overview.items as item (item.run.id)}
                        {@const state = crawlRunState(item.run)}
                        <Table.Row>
                          <Table.Cell class="max-w-72 whitespace-normal">
                            <Button
                              variant="link"
                              class="h-auto min-h-8 max-w-full justify-start px-0 text-left break-all whitespace-normal"
                              onclick={() => {
                                selectedRunId = item.run.id;
                                detailsOpen = true;
                              }}>{item.website_name || item.website_url}</Button
                            >
                            {#if item.website_name}
                              <p class="text-secondary mt-1 text-xs break-all">
                                {item.website_url}
                              </p>
                            {/if}
                          </Table.Cell>
                          <Table.Cell class="max-w-44 whitespace-normal"
                            >{item.space_name ?? "—"}</Table.Cell
                          >
                          <Table.Cell><CrawlRunStatus run={item.run} /></Table.Cell>
                          <Table.Cell><CrawlRunCounts run={item.run} /></Table.Cell>
                          <Table.Cell class="text-xs">
                            {#if state === "queued" && item.run.created_at}
                              {m.admin_crawler_wait({
                                duration: elapsed(item.run.created_at, overview.as_of)
                              })}
                            {:else if item.started_at}
                              <p>{m.admin_crawler_started({ time: date(item.started_at) })}</p>
                              <p class="text-secondary mt-1">
                                {elapsed(item.started_at, item.run.finished_at ?? overview.as_of)}
                              </p>
                            {:else}—{/if}
                          </Table.Cell>
                          <Table.Cell class="text-xs">{date(item.last_indexed_at)}</Table.Cell>
                        </Table.Row>
                      {:else}
                        <Table.Row
                          ><Table.Cell colspan={6} class="py-12 text-center">
                            {search || status !== "all"
                              ? m.admin_crawler_empty_filtered()
                              : view === "active"
                                ? m.admin_crawler_empty_active()
                                : m.admin_crawler_empty_recent()}
                          </Table.Cell></Table.Row
                        >
                      {/each}
                    </Table.Body>
                  </Table.Root>
                {/if}
              </div>
              <div class="flex flex-wrap items-center justify-between gap-3">
                <p class="text-secondary text-xs">
                  {overview
                    ? m.admin_crawler_fetched({ time: dayjs(overview.as_of).format("HH:mm:ss") })
                    : ""}
                </p>
                {#if cursors.length > 1 || overview?.next_cursor}
                  <div class="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={cursors.length === 1 || loading}
                      onclick={() => {
                        cursors = cursors.slice(0, -1);
                        rowsStale = true;
                        loadFailed = false;
                        void refresh();
                      }}>{m.admin_crawler_previous()}</Button
                    >
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={rowsStale || !overview?.next_cursor || loading}
                      onclick={() => {
                        if (overview?.next_cursor) {
                          cursors = [...cursors, overview.next_cursor];
                          rowsStale = true;
                          loadFailed = false;
                          void refresh();
                        }
                      }}>{m.admin_crawler_next()}</Button
                    >
                  </div>
                {/if}
              </div>
            </div>
          </Tabs.Content>
        {/key}
      </Tabs.Root>
    </div>
  </Page.Main>
</Page.Root>

{#if selectedRunId}
  <AdminCrawlDetails
    id={selectedRunId}
    bind:open={detailsOpen}
    onselect={(id) => {
      selectedRunId = id;
    }}
    onchange={() => {
      void refresh(true);
    }}
  />
{/if}
