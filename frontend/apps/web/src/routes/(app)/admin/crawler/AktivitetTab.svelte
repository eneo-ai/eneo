<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).
    See the LICENSE file at the repository root for the full license text.
-->

<script lang="ts">
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Pagination from "$lib/components/ui/pagination/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { CircleX, ListChecks, Search, TriangleAlert } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import { formatCrawlerCount } from "$lib/features/admin/crawlerNumberFormat";
  import {
    formatCrawlerScheduledCount,
    formatCrawlerScheduledIndexedSize,
    getCrawlerScheduledAggregateTotalLabel,
    getCrawlerScheduledIntervalLabel,
    getCrawlerScheduledUnparseableLabel,
    type CrawlerScheduledAggregateResponse
  } from "$lib/features/admin/crawlerScheduledAggregate";
  import type { CrawlerTenantWebsiteInventoryItem } from "$lib/features/admin/crawlerTenantWebsiteInventory";
  import {
    CRAWLER_LOW_RETENTION_THRESHOLD,
    CRAWLER_SOURCE_SKIP_DRIFT_MIN_INDEXED,
    CRAWLER_WEBSITE_PROCESSING_PAGE_SIZES,
    CRAWLER_WEBSITE_PROCESSING_SORT_OPTIONS,
    CRAWLER_WEBSITE_PROCESSING_TIME_WINDOWS,
    getCrawlerWebsiteProcessingFailureLabel,
    getCrawlerWebsiteProcessingFetchedLabel,
    getCrawlerWebsiteProcessingLatestRunEmbeddingUsageLabel,
    getCrawlerWebsiteProcessingLoadPressureLabel,
    getCrawlerWebsiteProcessingRetainedLabel,
    getCrawlerWebsiteProcessingSortLabel,
    getCrawlerWebsiteProcessingWebsiteLabel,
    isCrawlerWebsiteProcessingLowRetention,
    isCrawlerWebsiteProcessingPageSize,
    isCrawlerWebsiteProcessingSourceSkipDrift,
    isCrawlerWebsiteProcessingTimeWindow
  } from "$lib/features/admin/crawlerWebsiteProcessing";
  import EmptyState from "./EmptyState.svelte";
  import type { CrawlerActivityState } from "./crawlerActivityState.svelte";

  type ResolvedRowLabel = {
    label: string;
    inventoryItem: CrawlerTenantWebsiteInventoryItem | null;
  };

  type Props = {
    scheduledAggregate: CrawlerScheduledAggregateResponse | null;
    scheduledAggregateLoadFailed: boolean;
    activity: CrawlerActivityState;
    resolveRowLabel: (row: { website_id: string; website_name: string | null }) => ResolvedRowLabel;
    onOpenWebsiteDetail: (item: CrawlerTenantWebsiteInventoryItem) => void;
  };

  const {
    scheduledAggregate,
    scheduledAggregateLoadFailed,
    activity,
    resolveRowLabel,
    onOpenWebsiteDetail
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
</script>

<Card.Root class="mb-14" aria-labelledby="crawler-scheduled-title">
  <Card.Header>
    <div class="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
      <div class="flex min-w-0 flex-col gap-1">
        <h2 id="crawler-scheduled-title" class="text-base leading-snug font-semibold">
          {m.crawler_scheduled_title()}
        </h2>
        <Card.Description>{m.crawler_scheduled_description()}</Card.Description>
      </div>
      {#if scheduledAggregate}
        <Badge variant="outline" class="shrink-0 tabular-nums">
          {getCrawlerScheduledAggregateTotalLabel(scheduledAggregate)}
        </Badge>
      {/if}
    </div>
  </Card.Header>
  <Card.Content class="pt-0">
    {#if scheduledAggregateLoadFailed}
      <Alert.Root variant="destructive">
        <TriangleAlert aria-hidden="true" />
        <Alert.Description>{m.crawler_scheduled_load_error()}</Alert.Description>
      </Alert.Root>
    {:else if !scheduledAggregate || scheduledAggregate.total_websites === 0}
      <p class="text-muted-foreground text-sm">
        {m.crawler_scheduled_empty()}
      </p>
    {:else}
      {@const unparseableLabel = getCrawlerScheduledUnparseableLabel(scheduledAggregate)}
      <div class="flex flex-col gap-3">
        <div class="overflow-x-auto">
          <Table.Root class="min-w-[34rem]">
            <Table.Caption class="sr-only">
              {m.crawler_scheduled_table_caption()}
            </Table.Caption>
            <Table.Header>
              <Table.Row>
                <Table.Head>{m.crawler_scheduled_column_interval()}</Table.Head>
                <Table.Head class="text-right">
                  {m.crawler_scheduled_column_websites()}
                </Table.Head>
                <Table.Head class="text-right">
                  {m.crawler_scheduled_column_size()}
                </Table.Head>
              </Table.Row>
            </Table.Header>
            <Table.Body>
              {#each scheduledAggregate.buckets as bucket (bucket.update_interval)}
                <Table.Row>
                  <Table.Cell class="font-medium">
                    {getCrawlerScheduledIntervalLabel(bucket.update_interval)}
                  </Table.Cell>
                  <Table.Cell class="text-right tabular-nums">
                    {formatCrawlerScheduledCount(bucket.website_count)}
                  </Table.Cell>
                  <Table.Cell class="text-muted-foreground text-right tabular-nums">
                    {formatCrawlerScheduledIndexedSize(bucket.total_size_bytes)}
                  </Table.Cell>
                </Table.Row>
              {/each}
            </Table.Body>
          </Table.Root>
        </div>
        {#if unparseableLabel}
          <Alert.Root class="border-caution/35 bg-caution/8 dark:bg-caution/12">
            <TriangleAlert class="text-caution" aria-hidden="true" />
            <Alert.Description class="text-caution">
              {unparseableLabel}
            </Alert.Description>
          </Alert.Root>
        {/if}
      </div>
    {/if}
  </Card.Content>
</Card.Root>

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
      <!--
        sm+: 8-column table.
        Below sm: each row reflows to a stacked card so the operator
        can still read load pressure / retention / failures without
        horizontal scroll on a phone or narrow split-screen.
      -->
      <div
        class={["transition-opacity duration-200", activity.busy ? "opacity-60" : "opacity-100"]}
        aria-busy={activity.busy ? "true" : undefined}
      >
        <div class="hidden sm:block">
          <div class="overflow-x-auto">
            <Table.Root class="min-w-[66rem]">
              <Table.Caption class="sr-only">
                {m.crawler_website_processing_table_caption()}
              </Table.Caption>
              <Table.Header>
                <Table.Row>
                  <Table.Head>{m.crawler_website_processing_column_website()}</Table.Head>
                  <Table.Head>{m.crawler_website_processing_column_load_pressure()}</Table.Head>
                  <Table.Head>{m.crawler_website_processing_column_embedding_usage()}</Table.Head>
                  <Table.Head>{m.crawler_website_processing_column_runs()}</Table.Head>
                  <Table.Head>{m.crawler_website_processing_column_fetched()}</Table.Head>
                  <Table.Head>{m.crawler_website_processing_column_retained()}</Table.Head>
                  <Table.Head>{m.crawler_website_processing_column_failures()}</Table.Head>
                </Table.Row>
              </Table.Header>
              <Table.Body>
                {#each items as processingItem (processingItem.website_id)}
                  {@const failureLabel = getCrawlerWebsiteProcessingFailureLabel(processingItem)}
                  {@const processingResolved = resolveRowLabel(processingItem)}
                  {@const rowClickable = processingResolved.inventoryItem !== null}
                  <Table.Row
                    class={rowClickable
                      ? "hover:bg-muted/40 focus-within:bg-muted/40 cursor-pointer transition-colors"
                      : ""}
                    onclick={() =>
                      processingResolved.inventoryItem &&
                      onOpenWebsiteDetail(processingResolved.inventoryItem)}
                  >
                    <Table.Cell class="max-w-64">
                      <span
                        class="block truncate font-medium"
                        title={processingResolved.inventoryItem
                          ? processingResolved.label
                          : getCrawlerWebsiteProcessingWebsiteLabel(processingItem)}
                      >
                        {processingResolved.inventoryItem
                          ? processingResolved.label
                          : getCrawlerWebsiteProcessingWebsiteLabel(processingItem)}
                      </span>
                    </Table.Cell>
                    <Table.Cell>
                      <Badge
                        variant="outline"
                        class="tabular-nums"
                        title={m.crawler_website_processing_load_pressure_hint()}
                      >
                        {getCrawlerWebsiteProcessingLoadPressureLabel(processingItem)}
                      </Badge>
                    </Table.Cell>
                    <Table.Cell>
                      <Badge
                        variant="outline"
                        class="tabular-nums"
                        title={m.crawler_website_processing_embedding_usage_hint()}
                      >
                        {getCrawlerWebsiteProcessingLatestRunEmbeddingUsageLabel(processingItem)}
                      </Badge>
                    </Table.Cell>
                    <Table.Cell class="text-muted-foreground tabular-nums">
                      {m.crawler_website_processing_runs({
                        total: formatCrawlerCount(processingItem.total_runs),
                        terminal: formatCrawlerCount(processingItem.terminal_runs)
                      })}
                    </Table.Cell>
                    <Table.Cell class="tabular-nums">
                      {getCrawlerWebsiteProcessingFetchedLabel(processingItem)}
                    </Table.Cell>
                    <Table.Cell>
                      <div class="flex flex-wrap items-center gap-1.5">
                        <Badge
                          variant="outline"
                          class="border-accent-default/35 text-accent-default"
                        >
                          {getCrawlerWebsiteProcessingRetainedLabel(processingItem)}
                        </Badge>
                        {#if isCrawlerWebsiteProcessingLowRetention(processingItem, lowRetentionThreshold)}
                          <Badge
                            variant="outline"
                            class="border-caution/40 bg-caution/8 text-caution"
                            title={m.crawler_website_processing_low_retention_tooltip()}
                          >
                            {m.crawler_website_processing_low_retention_badge()}
                          </Badge>
                        {/if}
                        {#if isCrawlerWebsiteProcessingSourceSkipDrift(processingItem, sourceSkipDriftMinIndexed)}
                          <Badge
                            variant="outline"
                            class="border-caution/40 bg-caution/8 text-caution"
                            title={m.crawler_website_processing_source_skip_drift_tooltip()}
                          >
                            {m.crawler_website_processing_source_skip_drift_badge()}
                          </Badge>
                        {/if}
                      </div>
                    </Table.Cell>
                    <Table.Cell>
                      {#if failureLabel}
                        <Badge
                          variant="outline"
                          class="border-caution/40 bg-caution/8 text-caution"
                        >
                          {failureLabel}
                        </Badge>
                      {:else}
                        <span class="text-muted-foreground text-sm">
                          {m.crawler_website_processing_no_failures()}
                        </span>
                      {/if}
                    </Table.Cell>
                  </Table.Row>
                {/each}
              </Table.Body>
            </Table.Root>
          </div>
        </div>

        <ul
          class="flex flex-col gap-2 sm:hidden"
          aria-label={m.crawler_website_processing_table_caption()}
        >
          {#each items as processingItem (processingItem.website_id)}
            {@const failureLabel = getCrawlerWebsiteProcessingFailureLabel(processingItem)}
            {@const processingResolved = resolveRowLabel(processingItem)}
            {@const rowClickable = processingResolved.inventoryItem !== null}
            <li>
              <button
                type="button"
                class={[
                  "border-default bg-background flex w-full flex-col gap-2 rounded-lg border p-3 text-left transition-colors",
                  rowClickable
                    ? "hover:bg-muted/40 focus-visible:ring-ring/50 focus-visible:ring-2 focus-visible:outline-none"
                    : "cursor-default"
                ]}
                disabled={!rowClickable}
                onclick={() =>
                  processingResolved.inventoryItem &&
                  onOpenWebsiteDetail(processingResolved.inventoryItem)}
              >
                <span
                  class="block truncate text-sm font-medium"
                  title={processingResolved.inventoryItem
                    ? processingResolved.label
                    : getCrawlerWebsiteProcessingWebsiteLabel(processingItem)}
                >
                  {processingResolved.inventoryItem
                    ? processingResolved.label
                    : getCrawlerWebsiteProcessingWebsiteLabel(processingItem)}
                </span>
                <div class="flex flex-wrap items-center gap-1.5">
                  <Badge variant="outline" class="tabular-nums">
                    {getCrawlerWebsiteProcessingLoadPressureLabel(processingItem)}
                  </Badge>
                  <Badge variant="outline" class="border-accent-default/35 text-accent-default">
                    {getCrawlerWebsiteProcessingRetainedLabel(processingItem)}
                  </Badge>
                  {#if isCrawlerWebsiteProcessingLowRetention(processingItem, lowRetentionThreshold)}
                    <Badge variant="outline" class="border-caution/40 bg-caution/8 text-caution">
                      {m.crawler_website_processing_low_retention_badge()}
                    </Badge>
                  {/if}
                  {#if isCrawlerWebsiteProcessingSourceSkipDrift(processingItem, sourceSkipDriftMinIndexed)}
                    <Badge variant="outline" class="border-caution/40 bg-caution/8 text-caution">
                      {m.crawler_website_processing_source_skip_drift_badge()}
                    </Badge>
                  {/if}
                  {#if failureLabel}
                    <Badge variant="outline" class="border-caution/40 bg-caution/8 text-caution">
                      {failureLabel}
                    </Badge>
                  {/if}
                </div>
                <dl
                  class="text-muted-foreground grid grid-cols-2 gap-x-3 gap-y-1 text-xs tabular-nums"
                >
                  <dt>{m.crawler_website_processing_column_runs()}</dt>
                  <dd class="text-foreground text-right">
                    {m.crawler_website_processing_runs({
                      total: formatCrawlerCount(processingItem.total_runs),
                      terminal: formatCrawlerCount(processingItem.terminal_runs)
                    })}
                  </dd>
                  <dt>{m.crawler_website_processing_column_fetched()}</dt>
                  <dd class="text-foreground text-right">
                    {getCrawlerWebsiteProcessingFetchedLabel(processingItem)}
                  </dd>
                  <dt>{m.crawler_website_processing_column_embedding_usage()}</dt>
                  <dd class="text-foreground text-right">
                    {getCrawlerWebsiteProcessingLatestRunEmbeddingUsageLabel(processingItem)}
                  </dd>
                </dl>
              </button>
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
