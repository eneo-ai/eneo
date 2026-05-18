<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).
    See the LICENSE file at the repository root for the full license text.
-->

<script lang="ts">
  import { localizeHref } from "$lib/paraglide/runtime";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Pagination from "$lib/components/ui/pagination/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import {
    CheckCircle2,
    CircleX,
    Clock,
    Database,
    Eye,
    FileSearch,
    FolderKanban,
    HardDrive,
    ListChecks,
    MoreVertical,
    Play,
    Search,
    Trash2,
    TriangleAlert
  } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import { formatCrawlerDateTime } from "$lib/features/admin/crawlerPresentation";
  import { formatCrawlerCount } from "$lib/features/admin/crawlerNumberFormat";
  import { formatCrawlerScheduledIndexedSize } from "$lib/features/admin/crawlerScheduledAggregate";
  import type { CrawlerTenantWebsiteInventoryItem } from "$lib/features/admin/crawlerTenantWebsiteInventory";
  import {
    CRAWLER_LOW_RETENTION_THRESHOLD,
    CRAWLER_SOURCE_SKIP_DRIFT_MIN_INDEXED,
    CRAWLER_WEBSITE_PROCESSING_PAGE_SIZES,
    CRAWLER_WEBSITE_PROCESSING_SORT_OPTIONS,
    CRAWLER_WEBSITE_PROCESSING_TIME_WINDOWS,
    getCrawlerWebsiteProcessingFetchedLabel,
    getCrawlerWebsiteProcessingHealthSignal,
    getCrawlerWebsiteProcessingIndexedSizeLabel,
    getCrawlerWebsiteProcessingLatestRunEmbeddingUsageLabel,
    getCrawlerWebsiteProcessingOwnerLabel,
    getCrawlerWebsiteProcessingReuseLabel,
    getCrawlerWebsiteProcessingScheduleLabel,
    getCrawlerWebsiteProcessingSortLabel,
    getCrawlerWebsiteProcessingSpaceLabel,
    getCrawlerWebsiteProcessingUrlLabel,
    getCrawlerWebsiteProcessingWebsiteLabel,
    isCrawlerWebsiteProcessingPageSize,
    isCrawlerWebsiteProcessingTimeWindow,
    type CrawlerTenantWebsiteProcessingAggregateItem,
    type CrawlerTenantWebsiteProcessingAggregateResponse,
    type CrawlerWebsiteProcessingHealthSignal
  } from "$lib/features/admin/crawlerWebsiteProcessing";
  import EmptyState from "./EmptyState.svelte";
  import type { CrawlerActivityState } from "./crawlerActivityState.svelte";

  type ResolvedRowLabel = {
    label: string;
    inventoryItem: CrawlerTenantWebsiteInventoryItem | null;
  };

  type Props = {
    activity: CrawlerActivityState;
    resolveRowLabel: (row: { website_id: string; website_name: string | null }) => ResolvedRowLabel;
    onOpenWebsiteDetail: (item: CrawlerTenantWebsiteInventoryItem) => void;
    onOpenIntervalDialog: (item: CrawlerTenantWebsiteInventoryItem) => void;
    onOpenRetryDialog: (item: CrawlerTenantWebsiteInventoryItem) => void;
    onOpenDeleteDialog: (item: CrawlerTenantWebsiteInventoryItem) => void;
  };

  const {
    activity,
    resolveRowLabel,
    onOpenWebsiteDetail,
    onOpenIntervalDialog,
    onOpenRetryDialog,
    onOpenDeleteDialog
  }: Props = $props();

  const lowRetentionThreshold = $derived(
    activity.visible?.low_retention_threshold ?? CRAWLER_LOW_RETENTION_THRESHOLD
  );
  const sourceSkipDriftMinIndexed = $derived(
    activity.visible?.source_skip_drift_min_indexed ?? CRAWLER_SOURCE_SKIP_DRIFT_MIN_INDEXED
  );

  const items = $derived(activity.visible?.items ?? []);
  const total = $derived(activity.visible?.total ?? 0);
  const showingEnd = $derived(
    Math.min(total, (activity.page - 1) * activity.pageSize + items.length)
  );
  const showingStart = $derived(
    items.length === 0 ? 0 : (activity.page - 1) * activity.pageSize + 1
  );
  const hasItems = $derived(items.length > 0);
  const showingLabel = $derived(
    hasItems
      ? m.crawler_website_processing_count_range({
          start: formatCrawlerCount(showingStart),
          end: formatCrawlerCount(showingEnd),
          total: formatCrawlerCount(total)
        })
      : m.crawler_website_processing_count_total_only({ total: formatCrawlerCount(total) })
  );

  function chipClass(active: boolean): string {
    return active
      ? "border-accent-default bg-accent-default/10 text-accent-default ring-accent-default/20 inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium ring-2 transition-colors"
      : "border-border bg-background text-muted-foreground hover:border-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors";
  }

  function healthClass(state: CrawlerWebsiteProcessingHealthSignal): string {
    switch (state) {
      case "failure":
        return "border-destructive/35 bg-destructive/8 text-destructive";
      case "too_large":
      case "waste":
        return "border-caution/40 bg-caution/8 text-caution";
      case "healthy":
        return "border-positive-default/40 bg-positive-dimmer text-positive-stronger";
      default: {
        const exhaustive: never = state;
        return exhaustive;
      }
    }
  }

  function summaryEmbeddingLabel(
    summary: CrawlerTenantWebsiteProcessingAggregateResponse["summary"] | null | undefined
  ): string {
    if (
      !summary ||
      summary.embedding_input_tokens === null ||
      summary.embedding_input_tokens === undefined
    ) {
      return m.crawler_website_processing_summary_tokens_missing();
    }

    if (summary.embedding_input_tokens === 0) {
      return m.crawler_website_processing_embedding_usage_no_new_tokens();
    }
    return m.crawler_website_processing_summary_tokens_count({
      tokens: formatCrawlerCount(summary.embedding_input_tokens)
    });
  }

  function spaceEmbeddingLabel(
    space: CrawlerTenantWebsiteProcessingAggregateResponse["space_rollup"][number]
  ): string {
    if (space.embedding_input_tokens === null || space.embedding_input_tokens === undefined) {
      return m.crawler_website_processing_summary_tokens_missing();
    }

    if (space.embedding_input_tokens === 0) {
      return m.crawler_website_processing_embedding_usage_no_new_tokens();
    }
    return m.crawler_website_processing_summary_tokens_count({
      tokens: formatCrawlerCount(space.embedding_input_tokens)
    });
  }

  function spaceRollupName(
    space: CrawlerTenantWebsiteProcessingAggregateResponse["space_rollup"][number]
  ): string {
    return space.space_name?.trim() || m.crawler_website_processing_space_unknown();
  }

  function latestRunLabel(item: CrawlerTenantWebsiteProcessingAggregateItem): string {
    if (!item.latest_run_at) return m.crawler_website_processing_embedding_usage_unknown();
    return m.crawler_website_processing_latest_run({
      time: formatCrawlerDateTime(item.latest_run_at)
    });
  }

  function rowSecondaryLine(item: CrawlerTenantWebsiteProcessingAggregateItem): string {
    return m.crawler_website_processing_secondary_line({
      runs: m.crawler_website_processing_runs({
        total: formatCrawlerCount(item.total_runs),
        terminal: formatCrawlerCount(item.terminal_runs)
      }),
      fetched: getCrawlerWebsiteProcessingFetchedLabel(item),
      reuse: getCrawlerWebsiteProcessingReuseLabel(item)
    });
  }

  function inventoryOrNull(resolved: ResolvedRowLabel): CrawlerTenantWebsiteInventoryItem | null {
    return resolved.inventoryItem;
  }
</script>

<Card.Root class="mb-14" aria-labelledby="crawler-website-processing-title">
  <Card.Header>
    <div class="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
      <div class="flex min-w-0 flex-col gap-1">
        <h2 id="crawler-website-processing-title" class="text-base leading-snug font-semibold">
          {m.crawler_website_processing_title()}
        </h2>
        <Card.Description>
          {m.crawler_website_processing_description({ days: activity.days })}
        </Card.Description>
      </div>
      <Badge variant="outline" class="shrink-0 tabular-nums">
        {showingLabel}
      </Badge>
    </div>

    {#if activity.visible}
      {@const summary = activity.visible.summary}
      <div class="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <div class="border-default rounded-lg border p-3">
          <div class="flex items-center gap-2">
            <HardDrive class="text-muted-foreground size-4" aria-hidden="true" />
            <span class="text-muted-foreground text-xs font-medium tracking-wide uppercase">
              {m.crawler_website_processing_summary_indexed()}
            </span>
          </div>
          <p class="mt-2 text-lg font-semibold tabular-nums">
            {formatCrawlerScheduledIndexedSize(summary.indexed_size_bytes)}
          </p>
          <p class="text-muted-foreground mt-1 text-xs">
            {m.crawler_website_processing_summary_indexed_detail()}
          </p>
        </div>
        <div class="border-default rounded-lg border p-3">
          <div class="flex items-center gap-2">
            <Database class="text-muted-foreground size-4" aria-hidden="true" />
            <span class="text-muted-foreground text-xs font-medium tracking-wide uppercase">
              {m.crawler_website_processing_summary_tokens()}
            </span>
          </div>
          <p class="mt-2 text-lg font-semibold tabular-nums">
            {summaryEmbeddingLabel(summary)}
          </p>
          <p class="text-muted-foreground mt-1 text-xs">
            {m.crawler_website_processing_summary_tokens_detail()}
          </p>
        </div>
        <div class="border-default rounded-lg border p-3">
          <div class="flex items-center gap-2">
            <TriangleAlert class="text-muted-foreground size-4" aria-hidden="true" />
            <span class="text-muted-foreground text-xs font-medium tracking-wide uppercase">
              {m.crawler_website_processing_summary_actions()}
            </span>
          </div>
          <p class="mt-2 text-lg font-semibold tabular-nums">
            {formatCrawlerCount(summary.action_required_count)}
          </p>
          <p class="text-muted-foreground mt-1 text-xs">
            {m.crawler_website_processing_summary_actions_detail()}
          </p>
        </div>
        <div class="border-default rounded-lg border p-3">
          <div class="flex items-center gap-2">
            <ListChecks class="text-muted-foreground size-4" aria-hidden="true" />
            <span class="text-muted-foreground text-xs font-medium tracking-wide uppercase">
              {m.crawler_website_processing_summary_fetched()}
            </span>
          </div>
          <p class="mt-2 text-lg font-semibold tabular-nums">
            {m.crawler_website_processing_fetched({
              pages: formatCrawlerCount(summary.pages_crawled),
              files: formatCrawlerCount(summary.files_downloaded)
            })}
          </p>
          <!-- eslint-disable svelte/no-navigation-without-resolve -- localizeHref handles routing -->
          <a
            href={localizeHref("/admin/usage?tab=tokens")}
            class="text-accent-default mt-1 inline-flex text-xs font-medium hover:underline"
          >
            {m.crawler_website_processing_summary_usage_link()}
          </a>
          <!-- eslint-enable svelte/no-navigation-without-resolve -->
        </div>
      </div>
    {/if}

    {#if activity.visible?.space_rollup.length}
      <div class="border-default mt-4 rounded-lg border p-3">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="flex min-w-0 flex-col gap-1">
            <h3 class="text-sm leading-snug font-semibold">
              {m.crawler_website_processing_space_rollup_title()}
            </h3>
            <p class="text-muted-foreground text-xs">
              {m.crawler_website_processing_space_rollup_description({
                days: activity.days
              })}
            </p>
          </div>
          {#if activity.spaceId}
            <Button variant="ghost" size="sm" onclick={() => activity.setSpaceId(null)}>
              {m.crawler_website_processing_space_rollup_clear()}
            </Button>
          {/if}
        </div>
        <div class="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
          {#each activity.visible.space_rollup as space (space.space_id ?? "unknown-space")}
            {@const canFilterBySpace = space.space_id !== null}
            {@const isActive = canFilterBySpace && activity.spaceId === space.space_id}
            <button
              type="button"
              disabled={!canFilterBySpace}
              aria-pressed={isActive}
              aria-label={canFilterBySpace
                ? m.crawler_website_processing_space_rollup_filter_aria({
                    space: spaceRollupName(space)
                  })
                : m.crawler_website_processing_space_rollup_unknown_not_filterable()}
              class={[
                "border-default bg-background flex min-w-0 flex-col gap-2 rounded-lg border p-3 text-left transition-colors",
                canFilterBySpace
                  ? "hover:border-accent-default hover:bg-accent-default/5 focus-visible:ring-ring/50 focus-visible:ring-2 focus-visible:outline-none"
                  : "cursor-default opacity-80",
                isActive
                  ? "border-accent-default bg-accent-default/10 ring-accent-default/20 ring-2"
                  : ""
              ]}
              onclick={() => {
                if (space.space_id) {
                  activity.setSpaceId(activity.spaceId === space.space_id ? null : space.space_id);
                }
              }}
            >
              <span class="flex min-w-0 items-center gap-2">
                <FolderKanban class="text-muted-foreground size-4 shrink-0" aria-hidden="true" />
                <span class="truncate text-sm font-medium" title={spaceRollupName(space)}>
                  {spaceRollupName(space)}
                </span>
              </span>
              <span class="text-muted-foreground text-xs tabular-nums">
                {m.crawler_website_processing_space_rollup_websites({
                  websites: formatCrawlerCount(space.website_count)
                })}
              </span>
              <span class="text-xs tabular-nums">
                {formatCrawlerScheduledIndexedSize(space.indexed_size_bytes)}
              </span>
              <span class="text-muted-foreground truncate text-xs tabular-nums">
                {spaceEmbeddingLabel(space)}
              </span>
              {#if space.action_required_count > 0}
                <Badge variant="outline" class="border-caution/40 bg-caution/8 text-caution w-fit">
                  {m.crawler_website_processing_space_rollup_actions({
                    count: formatCrawlerCount(space.action_required_count)
                  })}
                </Badge>
              {/if}
            </button>
          {/each}
        </div>
      </div>
    {/if}

    <div class="bg-subtle border-default mt-4 flex flex-col gap-3 rounded-lg border p-3">
      <div class="flex flex-wrap items-center gap-2">
        <div class="relative min-w-[240px] flex-1">
          <Search
            class="text-muted-foreground pointer-events-none absolute top-1/2 left-2 size-4 -translate-y-1/2"
            aria-hidden="true"
          />
          <Input
            type="search"
            value={activity.search}
            oninput={(event) => activity.setSearch(event.currentTarget.value)}
            placeholder={m.crawler_website_processing_search_placeholder()}
            aria-label={m.crawler_website_processing_search_label()}
            class="pr-9 pl-8"
          />
          {#if activity.search.length > 0}
            <button
              type="button"
              class="text-muted-foreground hover:bg-muted focus-visible:ring-ring/50 absolute top-1/2 right-2 -translate-y-1/2 rounded p-1 transition-colors focus-visible:ring-2 focus-visible:outline-none"
              aria-label={m.crawler_website_processing_search_clear()}
              onclick={() => activity.clearSearch()}
            >
              <CircleX class="size-4" aria-hidden="true" />
            </button>
          {/if}
        </div>
        {#if activity.activeFilterCount > 0}
          <Button variant="ghost" size="sm" onclick={() => activity.clearFilters()}>
            {m.crawler_website_processing_clear_filters()}
          </Button>
        {/if}
      </div>

      <div class="flex flex-col gap-1.5">
        <span class="text-muted-foreground text-[10px] font-medium tracking-wide uppercase">
          {m.crawler_website_processing_filter_group_window()}
        </span>
        <div
          role="group"
          aria-label={m.crawler_website_processing_filter_group_window()}
          class="flex flex-wrap gap-1.5"
        >
          {#each CRAWLER_WEBSITE_PROCESSING_TIME_WINDOWS as window (window)}
            {@const isActive = activity.days === window}
            <button
              type="button"
              aria-pressed={isActive}
              class={chipClass(isActive)}
              onclick={() => {
                if (isCrawlerWebsiteProcessingTimeWindow(window)) activity.setDays(window);
              }}
            >
              {m.crawler_website_processing_filter_window_days({ days: window })}
            </button>
          {/each}
        </div>
      </div>

      <div class="flex flex-col gap-1.5">
        <span class="text-muted-foreground text-[10px] font-medium tracking-wide uppercase">
          {m.crawler_website_processing_filter_group_sort()}
        </span>
        <div
          role="group"
          aria-label={m.crawler_website_processing_filter_group_sort()}
          class="flex flex-wrap gap-1.5"
        >
          {#each CRAWLER_WEBSITE_PROCESSING_SORT_OPTIONS as option (option)}
            {@const isActive = activity.sort === option}
            <button
              type="button"
              aria-pressed={isActive}
              class={chipClass(isActive)}
              onclick={() => activity.setSort(option)}
            >
              {getCrawlerWebsiteProcessingSortLabel(option)}
            </button>
          {/each}
        </div>
      </div>

      <div class="flex flex-col gap-1.5">
        <span class="text-muted-foreground text-[10px] font-medium tracking-wide uppercase">
          {m.crawler_website_processing_filter_group_focus()}
        </span>
        <div
          role="group"
          aria-label={m.crawler_website_processing_filter_group_focus()}
          class="flex flex-wrap gap-1.5"
        >
          <button
            type="button"
            aria-pressed={activity.filters.failuresOnly}
            class={chipClass(activity.filters.failuresOnly)}
            onclick={() => activity.setFailuresOnly(!activity.filters.failuresOnly)}
          >
            {m.crawler_website_processing_filter_failures_only()}
          </button>
          <button
            type="button"
            aria-pressed={activity.filters.lowRetentionOnly}
            class={chipClass(activity.filters.lowRetentionOnly)}
            onclick={() => activity.setLowRetentionOnly(!activity.filters.lowRetentionOnly)}
          >
            {m.crawler_website_processing_filter_low_retention()}
          </button>
          <button
            type="button"
            aria-pressed={activity.filters.sourceSkipDriftOnly}
            class={chipClass(activity.filters.sourceSkipDriftOnly)}
            onclick={() => activity.setSourceSkipDriftOnly(!activity.filters.sourceSkipDriftOnly)}
          >
            {m.crawler_website_processing_filter_source_skip_drift()}
          </button>
        </div>
      </div>
    </div>
  </Card.Header>

  <Card.Content class="pt-0">
    {#if activity.loadFailed && !activity.visible}
      <Alert.Root variant="destructive">
        <TriangleAlert aria-hidden="true" />
        <Alert.Description>{m.crawler_website_processing_load_error()}</Alert.Description>
      </Alert.Root>
    {:else if activity.busy && !activity.visible}
      <div class="flex flex-col gap-2" aria-busy="true" aria-live="polite">
        {#each Array(activity.pageSize) as _, idx (idx)}
          <Skeleton class="h-10 w-full" />
        {/each}
        <span class="sr-only">{m.crawler_website_processing_loading()}</span>
      </div>
    {:else if !hasItems}
      {#if activity.activeFilterCount > 0}
        <EmptyState
          title={m.crawler_website_processing_filtered_empty_title()}
          description={m.crawler_website_processing_filtered_empty_description()}
        >
          {#snippet icon()}
            <ListChecks class="size-5" />
          {/snippet}
          {#snippet actions()}
            <Button variant="ghost" size="sm" onclick={() => activity.clearFilters()}>
              {m.crawler_website_processing_clear_filters()}
            </Button>
          {/snippet}
        </EmptyState>
      {:else}
        <p class="text-muted-foreground text-sm">
          {m.crawler_website_processing_empty({ days: activity.days })}
        </p>
      {/if}
    {:else}
      <div
        class={["transition-opacity duration-200", activity.busy ? "opacity-60" : "opacity-100"]}
        aria-busy={activity.busy ? "true" : undefined}
      >
        <div class="hidden md:block">
          <Table.Root class="w-full table-fixed">
            <Table.Caption class="sr-only">
              {m.crawler_website_processing_table_caption()}
            </Table.Caption>
            <Table.Header>
              <Table.Row>
                <Table.Head class="w-[36%]">
                  {m.crawler_website_processing_column_website()}
                </Table.Head>
                <Table.Head class="w-[12%]">
                  {m.crawler_website_processing_column_schedule()}
                </Table.Head>
                <Table.Head class="w-[12%] text-right">
                  {m.crawler_website_processing_column_indexed_size()}
                </Table.Head>
                <Table.Head class="w-[18%]">
                  {m.crawler_website_processing_column_embedding_usage()}
                </Table.Head>
                <Table.Head class="w-[14%]">
                  {m.crawler_website_processing_column_health()}
                </Table.Head>
                <Table.Head class="w-[8%] text-right">
                  <span class="sr-only">
                    {m.crawler_website_processing_column_actions()}
                  </span>
                </Table.Head>
              </Table.Row>
            </Table.Header>
            <Table.Body>
              {#each items as processingItem (processingItem.website_id)}
                {@const processingResolved = resolveRowLabel(processingItem)}
                {@const inventoryItem = inventoryOrNull(processingResolved)}
                {@const rowClickable = inventoryItem !== null}
                {@const health = getCrawlerWebsiteProcessingHealthSignal(processingItem, {
                  lowRetentionThreshold,
                  sourceSkipDriftMinIndexed
                })}
                <Table.Row
                  class={rowClickable
                    ? "hover:bg-muted/40 focus-within:bg-muted/40 cursor-pointer transition-colors"
                    : ""}
                  onclick={() => inventoryItem && onOpenWebsiteDetail(inventoryItem)}
                >
                  <Table.Cell class="min-w-0 align-top">
                    <div class="flex min-w-0 flex-col gap-1">
                      <span
                        class="truncate font-medium"
                        title={getCrawlerWebsiteProcessingWebsiteLabel(processingItem)}
                      >
                        {getCrawlerWebsiteProcessingWebsiteLabel(processingItem)}
                      </span>
                      <span
                        class="text-muted-foreground truncate text-xs"
                        title={`${getCrawlerWebsiteProcessingSpaceLabel(processingItem)} · ${getCrawlerWebsiteProcessingOwnerLabel(processingItem)}`}
                      >
                        {getCrawlerWebsiteProcessingSpaceLabel(processingItem)} · {getCrawlerWebsiteProcessingOwnerLabel(
                          processingItem
                        )}
                      </span>
                      <span class="text-muted-foreground truncate text-xs tabular-nums">
                        {rowSecondaryLine(processingItem)}
                      </span>
                    </div>
                  </Table.Cell>
                  <Table.Cell class="align-top text-sm">
                    {getCrawlerWebsiteProcessingScheduleLabel(processingItem)}
                  </Table.Cell>
                  <Table.Cell class="text-right align-top text-sm tabular-nums">
                    {getCrawlerWebsiteProcessingIndexedSizeLabel(processingItem)}
                  </Table.Cell>
                  <Table.Cell class="align-top">
                    <Badge
                      variant="outline"
                      class="max-w-full truncate tabular-nums"
                      title={m.crawler_website_processing_embedding_usage_hint()}
                    >
                      {getCrawlerWebsiteProcessingLatestRunEmbeddingUsageLabel(processingItem)}
                    </Badge>
                    <div class="text-muted-foreground mt-1 text-xs">
                      {latestRunLabel(processingItem)}
                    </div>
                  </Table.Cell>
                  <Table.Cell class="align-top">
                    <Badge
                      variant="outline"
                      class={healthClass(health.state)}
                      title={health.detail}
                    >
                      {#if health.state === "healthy"}
                        <CheckCircle2 class="size-3.5" aria-hidden="true" />
                      {:else}
                        <TriangleAlert class="size-3.5" aria-hidden="true" />
                      {/if}
                      {health.label}
                    </Badge>
                  </Table.Cell>
                  <Table.Cell
                    class="text-right align-top"
                    onclick={(event) => event.stopPropagation()}
                  >
                    <DropdownMenu.Root>
                      <DropdownMenu.Trigger>
                        {#snippet child({ props })}
                          <Button
                            {...props}
                            variant="ghost"
                            size="icon"
                            class="size-8"
                            aria-label={m.crawler_website_processing_row_actions_aria({
                              website: getCrawlerWebsiteProcessingWebsiteLabel(processingItem)
                            })}
                          >
                            <MoreVertical class="size-4" />
                          </Button>
                        {/snippet}
                      </DropdownMenu.Trigger>
                      <DropdownMenu.Content align="end" class="min-w-56">
                        <DropdownMenu.Item
                          disabled={!inventoryItem}
                          onclick={() => inventoryItem && onOpenWebsiteDetail(inventoryItem)}
                        >
                          <Eye class="size-4" />
                          {m.crawler_inventory_row_action_view_detail()}
                        </DropdownMenu.Item>
                        <DropdownMenu.Separator />
                        <DropdownMenu.Item
                          disabled={!inventoryItem}
                          onclick={() => inventoryItem && onOpenRetryDialog(inventoryItem)}
                        >
                          <Play class="size-4" />
                          {m.crawler_website_detail_action_retry()}
                        </DropdownMenu.Item>
                        <DropdownMenu.Item
                          disabled={!inventoryItem}
                          onclick={() => inventoryItem && onOpenIntervalDialog(inventoryItem)}
                        >
                          <Clock class="size-4" />
                          {m.crawler_website_detail_action_interval()}
                        </DropdownMenu.Item>
                        <DropdownMenu.Separator />
                        <!-- eslint-disable svelte/no-navigation-without-resolve -- localizeHref handles routing -->
                        <DropdownMenu.Item>
                          {#snippet child({ props })}
                            <a
                              {...props}
                              href={localizeHref(
                                `/admin/audit-logs?tab=logs&search=${encodeURIComponent(
                                  getCrawlerWebsiteProcessingUrlLabel(processingItem)
                                )}`
                              )}
                            >
                              <FileSearch class="size-4" />
                              {m.crawler_inventory_row_action_audit_logs()}
                            </a>
                          {/snippet}
                        </DropdownMenu.Item>
                        <!-- eslint-enable svelte/no-navigation-without-resolve -->
                        <DropdownMenu.Separator />
                        <DropdownMenu.Item
                          variant="destructive"
                          disabled={!inventoryItem}
                          onclick={() => inventoryItem && onOpenDeleteDialog(inventoryItem)}
                        >
                          <Trash2 class="size-4" />
                          {m.crawler_website_detail_action_delete()}
                        </DropdownMenu.Item>
                      </DropdownMenu.Content>
                    </DropdownMenu.Root>
                  </Table.Cell>
                </Table.Row>
              {/each}
            </Table.Body>
          </Table.Root>
        </div>

        <ul
          class="flex flex-col gap-2 md:hidden"
          aria-label={m.crawler_website_processing_table_caption()}
        >
          {#each items as processingItem (processingItem.website_id)}
            {@const processingResolved = resolveRowLabel(processingItem)}
            {@const inventoryItem = inventoryOrNull(processingResolved)}
            {@const health = getCrawlerWebsiteProcessingHealthSignal(processingItem, {
              lowRetentionThreshold,
              sourceSkipDriftMinIndexed
            })}
            <li class="border-default bg-background rounded-lg border p-3">
              <div class="flex items-start justify-between gap-3">
                <button
                  type="button"
                  class={[
                    "min-w-0 flex-1 text-left",
                    inventoryItem
                      ? "hover:text-accent-default focus-visible:ring-ring/50 rounded focus-visible:ring-2 focus-visible:outline-none"
                      : "cursor-default"
                  ]}
                  disabled={!inventoryItem}
                  onclick={() => inventoryItem && onOpenWebsiteDetail(inventoryItem)}
                >
                  <span
                    class="block truncate text-sm font-medium"
                    title={getCrawlerWebsiteProcessingWebsiteLabel(processingItem)}
                  >
                    {getCrawlerWebsiteProcessingWebsiteLabel(processingItem)}
                  </span>
                  <span class="text-muted-foreground mt-1 block truncate text-xs">
                    {getCrawlerWebsiteProcessingSpaceLabel(processingItem)} · {getCrawlerWebsiteProcessingOwnerLabel(
                      processingItem
                    )}
                  </span>
                </button>
                <Badge variant="outline" class={healthClass(health.state)} title={health.detail}>
                  {health.label}
                </Badge>
              </div>
              <dl class="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
                <dt class="text-muted-foreground">
                  {m.crawler_website_processing_column_schedule()}
                </dt>
                <dd class="text-right">
                  {getCrawlerWebsiteProcessingScheduleLabel(processingItem)}
                </dd>
                <dt class="text-muted-foreground">
                  {m.crawler_website_processing_column_indexed_size()}
                </dt>
                <dd class="text-right tabular-nums">
                  {getCrawlerWebsiteProcessingIndexedSizeLabel(processingItem)}
                </dd>
                <dt class="text-muted-foreground">
                  {m.crawler_website_processing_column_embedding_usage()}
                </dt>
                <dd class="text-right tabular-nums">
                  {getCrawlerWebsiteProcessingLatestRunEmbeddingUsageLabel(processingItem)}
                </dd>
                <dt class="text-muted-foreground">
                  {m.crawler_website_processing_column_fetched()}
                </dt>
                <dd class="text-right tabular-nums">
                  {getCrawlerWebsiteProcessingFetchedLabel(processingItem)}
                </dd>
              </dl>
              <p class="text-muted-foreground mt-3 text-xs tabular-nums">
                {rowSecondaryLine(processingItem)}
              </p>
            </li>
          {/each}
        </ul>
      </div>

      <div class="mt-3 flex flex-wrap items-center justify-between gap-3">
        <label class="text-muted-foreground flex items-center gap-2 text-xs">
          <span>{m.crawler_website_processing_page_size_label()}</span>
          <select
            class="border-default bg-background text-foreground focus-visible:ring-ring/50 rounded-md border px-2 py-1 text-xs tabular-nums focus-visible:ring-2 focus-visible:outline-none"
            value={activity.pageSize}
            onchange={(event) => {
              const next = Number(event.currentTarget.value);
              if (isCrawlerWebsiteProcessingPageSize(next)) activity.setPageSize(next);
            }}
          >
            {#each CRAWLER_WEBSITE_PROCESSING_PAGE_SIZES as size (size)}
              <option value={size}>{size}</option>
            {/each}
          </select>
        </label>

        <Pagination.Root
          count={total}
          perPage={activity.pageSize}
          page={activity.page}
          onPageChange={(next) => activity.setPage(next)}
          class="m-0 w-auto justify-end"
        >
          {#snippet children({ pages, currentPage })}
            <Pagination.Content>
              <Pagination.Item>
                <Pagination.PrevButton />
              </Pagination.Item>
              {#each pages as p (p.key)}
                {#if p.type === "ellipsis"}
                  <Pagination.Item>
                    <Pagination.Ellipsis />
                  </Pagination.Item>
                {:else}
                  <Pagination.Item>
                    <Pagination.Link page={p} isActive={currentPage === p.value}>
                      {p.value}
                    </Pagination.Link>
                  </Pagination.Item>
                {/if}
              {/each}
              <Pagination.Item>
                <Pagination.NextButton />
              </Pagination.Item>
            </Pagination.Content>
          {/snippet}
        </Pagination.Root>
      </div>
    {/if}
  </Card.Content>
</Card.Root>
