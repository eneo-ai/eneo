<script lang="ts">
  import { onMount } from "svelte";
  import dayjs from "dayjs";
  import type { AdminCrawlerOverview, AdminCrawlerQuery } from "@eneo/eneo-js";
  import { ArrowRight, RefreshCw } from "lucide-svelte";
  import { Page } from "$lib/components/layout";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import * as Tabs from "$lib/components/ui/tabs/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import AdminCrawlDetails from "./AdminCrawlDetails.svelte";
  import {
    crawlRunState,
    crawlRunStateLabel,
    type CrawlRunState
  } from "$lib/features/knowledge/crawlRunState";
  import { m } from "$lib/paraglide/messages";

  const eneo = getEneo();
  type Status = "all" | "issues" | Exclude<CrawlRunState, "unknown">;
  let view = $state<"active" | "recent">("active");
  let status = $state<Status>("all");
  let searchInput = $state("");
  let search = $state("");
  let cursors = $state<(string | null)[]>([null]);
  let overview = $state<AdminCrawlerOverview | null>(null);
  let loading = $state(false);
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
          "succeeded",
          "unchanged",
          "empty",
          "partial",
          "failed",
          "cancelled",
          "interrupted"
        ]
  );

  function query(): AdminCrawlerQuery {
    return {
      view,
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
    loadFailed = false;
    try {
      const result = await eneo.adminCrawler.overview(request);
      if (mounted && requestKey === JSON.stringify(query())) overview = result;
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
    overview = null;
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
    search = "";
    searchInput = "";
    filterChanged();
  }

  function statusLabel(value: Status) {
    if (value === "all") return m.admin_crawler_all_statuses();
    if (value === "issues") return m.admin_crawler_issues();
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
      <div class="grid gap-3 sm:grid-cols-3">
        <Card.Root>
          <Card.Header>
            <Card.Title>{m.admin_crawler_ongoing()}</Card.Title>
            <Card.Description>{m.admin_crawler_now()}</Card.Description>
          </Card.Header>
          <Card.Content>
            {#if overview}<p class="text-3xl font-semibold tabular-nums">
                {overview.summary.ongoing}
              </p>{:else}<Skeleton class="h-9 w-16" />{/if}
          </Card.Content>
        </Card.Root>
        <Card.Root>
          <Card.Header>
            <Card.Title>{m.admin_crawler_queued()}</Card.Title>
            <Card.Description>{m.admin_crawler_now()}</Card.Description>
          </Card.Header>
          <Card.Content>
            {#if overview}<p class="text-3xl font-semibold tabular-nums">
                {overview.summary.queued}
              </p>{:else}<Skeleton class="h-9 w-16" />{/if}
          </Card.Content>
        </Card.Root>
        <Card.Root>
          <Card.Header>
            <Card.Title>{m.admin_crawler_issues()}</Card.Title>
            <Card.Description>{m.admin_crawler_last_day()}</Card.Description>
            <Card.Action
              ><Button
                variant="ghost"
                size="icon-sm"
                onclick={showIssues}
                aria-label={m.admin_crawler_show_issues()}
                title={m.admin_crawler_show_issues()}><ArrowRight /></Button
              ></Card.Action
            >
          </Card.Header>
          <Card.Content>
            {#if overview}<p class="text-3xl font-semibold tabular-nums">
                {overview.summary.issues}
              </p>{:else}<Skeleton class="h-9 w-16" />{/if}
          </Card.Content>
        </Card.Root>
      </div>

      <Tabs.Root value={view} onValueChange={changeView}>
        <Tabs.List aria-label={m.admin_crawler_title()}>
          <Tabs.Trigger value="active">{m.admin_crawler_active()}</Tabs.Trigger>
          <Tabs.Trigger value="recent">{m.admin_crawler_last_day()}</Tabs.Trigger>
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
              </form>

              {#if loadFailed}
                <Alert.Root variant="destructive">
                  <Alert.Description>{m.admin_crawler_error()}</Alert.Description>
                  <Alert.Action
                    ><Button variant="outline" size="sm" onclick={() => refresh()}
                      >{m.retry()}</Button
                    ></Alert.Action
                  >
                </Alert.Root>
              {/if}

              <div aria-busy={loading}>
                {#if !overview && !loadFailed}
                  <div class="flex flex-col gap-3" role="status" aria-label={m.loading()}>
                    {#each [1, 2, 3] as row (row)}<Skeleton class="h-16 w-full" />{/each}
                  </div>
                {:else if overview}
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
                            <button
                              type="button"
                              class="text-accent-default text-left font-medium break-all underline-offset-4 hover:underline focus-visible:underline"
                              onclick={() => {
                                selectedRunId = item.run.id;
                                detailsOpen = true;
                              }}>{item.website_name || item.website_url}</button
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
                          <Table.Cell
                            ><Badge
                              variant={state === "failed" || state === "interrupted"
                                ? "destructive"
                                : "secondary"}>{crawlRunStateLabel(state)}</Badge
                            ></Table.Cell
                          >
                          <Table.Cell
                            ><div class="flex flex-col gap-1 text-xs">
                              <span
                                >{m.pages_succeeded({ count: item.run.pages_crawled ?? "—" })}</span
                              >
                              <span
                                >{m.files_succeeded({
                                  count: item.run.files_downloaded ?? "—"
                                })}</span
                              >
                              {#if item.run.pages_failed}<span
                                  >{m.pages_failed({ count: item.run.pages_failed })}</span
                                >{/if}
                              {#if item.run.files_failed}<span
                                  >{m.files_failed({ count: item.run.files_failed })}</span
                                >{/if}
                            </div></Table.Cell
                          >
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
                        overview = null;
                        void refresh();
                      }}>{m.admin_crawler_previous()}</Button
                    >
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={!overview?.next_cursor || loading}
                      onclick={() => {
                        if (overview?.next_cursor) {
                          cursors = [...cursors, overview.next_cursor];
                          overview = null;
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
