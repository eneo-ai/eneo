<script lang="ts">
  import dayjs from "dayjs";
  import type { AdminCrawlerScheduledWebsite } from "@eneo/eneo-js";
  import { Clock3, LoaderCircle, TriangleAlert } from "lucide-svelte";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import CrawlRunStatus from "$lib/features/knowledge/CrawlRunStatus.svelte";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import { intervalLabel, relativeDue, sortDirections, type ScheduleSort } from "./scheduleFormat";

  let {
    items,
    asOf,
    sort,
    filtered,
    onsort,
    onselect
  }: {
    items: AdminCrawlerScheduledWebsite[];
    asOf: string;
    sort: ScheduleSort;
    filtered: boolean;
    onsort: (sort: ScheduleSort) => void;
    onselect: (runId: string) => void;
  } = $props();

  function date(value: string | null | undefined) {
    return value ? dayjs(value).format("YYYY-MM-DD HH:mm") : "—";
  }

  function stateLabel(item: AdminCrawlerScheduledWebsite) {
    switch (item.schedule_state) {
      case "due":
        return m.admin_crawler_state_due();
      case "waiting":
        return m.admin_crawler_state_waiting();
      case "blocked_active_run":
        return m.admin_crawler_state_blocked_active();
      case "blocked_backoff":
        return m.admin_crawler_state_blocked_backoff({
          time: date(item.blocked_until ?? item.next_retry_at)
        });
      default:
        return m.disabled();
    }
  }
</script>

{#snippet sortHeader(field: ScheduleSort, label: string)}
  <Table.Head aria-sort={sort === field ? sortDirections[field] : "none"}>
    <Button
      variant="ghost"
      class="-ml-2"
      aria-label={m.admin_crawler_sort_by({ column: label })}
      aria-pressed={sort === field}
      onclick={() => onsort(field)}
    >
      {label}<span aria-hidden="true"
        >{sort === field ? (sortDirections[field] === "ascending" ? "↑" : "↓") : "↕"}</span
      >
    </Button>
  </Table.Head>
{/snippet}

<Table.Root class="min-w-[1100px]">
  <Table.Caption class="sr-only">{m.admin_crawler_schedule_caption()}</Table.Caption>
  <Table.Header
    ><Table.Row>
      {@render sortHeader("url", m.website())}
      <Table.Head>{m.admin_crawler_space()}</Table.Head>
      <Table.Head>{m.admin_crawler_interval()}</Table.Head>
      {@render sortHeader("last_crawled", m.admin_crawler_last_crawled())}
      {@render sortHeader("next_due", m.admin_crawler_next_due())}
      <Table.Head>{m.status()}</Table.Head>
      <Table.Head>{m.failures()}</Table.Head>
    </Table.Row></Table.Header
  >
  <Table.Body>
    {#each items as item (item.website_id)}
      <Table.Row>
        <Table.Cell class="max-w-72 whitespace-normal">
          {#if item.latest_run}
            <Button
              variant="link"
              class="h-auto min-h-8 max-w-full justify-start px-0 text-left break-all whitespace-normal"
              onclick={() => onselect(item.latest_run!.id)}
              >{item.website_name || item.website_url}</Button
            >
          {:else}
            <p class="break-all">{item.website_name || item.website_url}</p>
            <p class="text-secondary mt-1 text-xs">{m.admin_crawler_no_run()}</p>
          {/if}
          {#if item.website_name}
            <p class="text-secondary mt-1 text-xs break-all">{item.website_url}</p>
          {/if}
        </Table.Cell>
        <Table.Cell class="max-w-44 whitespace-normal">{item.space_name ?? "—"}</Table.Cell>
        <Table.Cell>{intervalLabel(item.update_interval)}</Table.Cell>
        <Table.Cell class="text-xs">
          <p>{date(item.last_crawled_at)}</p>
          {#if item.latest_run}
            <div class="mt-1"><CrawlRunStatus run={item.latest_run} /></div>
          {/if}
        </Table.Cell>
        <Table.Cell class="text-xs">
          {#if item.next_due_at}
            <p>{date(item.next_due_at)}</p>
            <p class="text-secondary mt-1">{relativeDue(item.next_due_at, asOf, getLocale())}</p>
          {:else}—{/if}
        </Table.Cell>
        <Table.Cell>
          <Badge
            variant={item.schedule_state === "disabled" ? "outline" : "secondary"}
            class={item.schedule_state === "due" || item.schedule_state === "blocked_active_run"
              ? "bg-accent-dimmer text-accent-stronger"
              : item.schedule_state === "blocked_backoff"
                ? "bg-warning-dimmer text-warning-stronger"
                : undefined}
          >
            {#if item.schedule_state === "due"}<Clock3
                aria-hidden="true"
                data-icon="inline-start"
              />
            {:else if item.schedule_state === "blocked_active_run"}<LoaderCircle
                aria-hidden="true"
                data-icon="inline-start"
              />
            {:else if item.schedule_state === "blocked_backoff"}<TriangleAlert
                aria-hidden="true"
                data-icon="inline-start"
              />{/if}
            {stateLabel(item)}
          </Badge>
        </Table.Cell>
        <Table.Cell class="text-xs tabular-nums">
          <p>{item.consecutive_failures}</p>
          {#if item.consecutive_failures > 0 && item.next_retry_at}
            <p class="text-secondary mt-1">
              {m.admin_crawler_retry_after({ time: date(item.next_retry_at) })}
            </p>
          {/if}
        </Table.Cell>
      </Table.Row>
    {:else}
      <Table.Row
        ><Table.Cell colspan={7} class="py-12 text-center">
          {filtered ? m.admin_crawler_schedule_empty_filtered() : m.admin_crawler_schedule_empty()}
        </Table.Cell></Table.Row
      >
    {/each}
  </Table.Body>
</Table.Root>
