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
  import * as Select from "$lib/components/ui/select/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import * as ToggleGroup from "$lib/components/ui/toggle-group/index.js";
  import { CircleX, Inbox, ListChecks, TriangleAlert } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import {
    CRAWLER_ACTIVE_INVENTORY_LIFECYCLE_FILTER_OPTIONS,
    CRAWLER_ACTIVE_INVENTORY_PAGE_SIZES,
    canAbortCrawlerActiveInventoryItem,
    getCrawlerActiveInventoryLifecycleFilterLabel,
    getCrawlerActiveInventoryResultLabels,
    getCrawlerActiveInventorySourceLabel,
    getCrawlerActiveInventoryStartedByLabel,
    getCrawlerActiveInventoryStatusLabel,
    getCrawlerActiveInventoryWebsiteLabel,
    isCrawlerActiveInventoryItemRunning,
    type CrawlerActiveInventoryItem,
    type CrawlerActiveInventoryLifecycleFilter,
    type CrawlerActiveInventoryPageSize,
    type CrawlerActiveInventoryResponse
  } from "$lib/features/admin/crawlerActiveInventory";
  import {
    crawlerActiveStatusBadgeClass,
    crawlerResultBadgeClass,
    formatCrawlerDateTime
  } from "$lib/features/admin/crawlerPresentation";
  import type { CrawlerTenantWebsiteInventoryItem } from "$lib/features/admin/crawlerTenantWebsiteInventory";
  import EmptyState from "./EmptyState.svelte";

  type ResolvedRowLabel = {
    label: string;
    inventoryItem: CrawlerTenantWebsiteInventoryItem | null;
  };

  type Props = {
    activeInventory: CrawlerActiveInventoryResponse | null;
    visibleItems: readonly CrawlerActiveInventoryItem[];
    lifecycleFilter: CrawlerActiveInventoryLifecycleFilter;
    filterBusy: boolean;
    loadFailed: boolean;
    page: number;
    pageSize: CrawlerActiveInventoryPageSize;
    search: string;
    savingIntervalWebsiteId: string | null;
    abortingJobId: string | null;
    resolveRowLabel: (row: { website_id: string; website_name: string | null }) => ResolvedRowLabel;
    onOpenWebsiteDetail: (item: CrawlerTenantWebsiteInventoryItem) => void;
    onOpenIntervalDialog: (item: CrawlerActiveInventoryItem) => void;
    onOpenAbortDialog: (item: CrawlerActiveInventoryItem) => void;
    onRefresh: (options: { filter?: CrawlerActiveInventoryLifecycleFilter; page?: number }) => void;
    onPageSizeChange: (value: string) => void;
  };

  let {
    activeInventory,
    visibleItems,
    lifecycleFilter,
    filterBusy,
    loadFailed,
    page,
    pageSize,
    search = $bindable(),
    savingIntervalWebsiteId,
    abortingJobId,
    resolveRowLabel,
    onOpenWebsiteDetail,
    onOpenIntervalDialog,
    onOpenAbortDialog,
    onRefresh,
    onPageSizeChange
  }: Props = $props();
</script>

<Card.Root class="mb-14" aria-labelledby="crawler-active-inventory-title">
  <Card.Header>
    <div class="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
      <div class="flex min-w-0 flex-col gap-1">
        <h2 id="crawler-active-inventory-title" class="text-base leading-snug font-semibold">
          {m.crawler_active_inventory_title()}
        </h2>
        <Card.Description>{m.crawler_active_inventory_description()}</Card.Description>
      </div>
      {#if activeInventory}
        <Badge variant="outline" class="shrink-0 tabular-nums">
          {m.crawler_active_inventory_count({
            shown: activeInventory.items.length,
            total: activeInventory.total
          })}
        </Badge>
      {/if}
    </div>
    <div class="flex flex-wrap items-end gap-3 pt-3">
      <ToggleGroup.Root
        type="single"
        variant="outline"
        size="sm"
        value={lifecycleFilter}
        onValueChange={(next) => {
          if (next) {
            onRefresh({ filter: next as CrawlerActiveInventoryLifecycleFilter });
          }
        }}
        aria-label={m.crawler_active_inventory_filter_label()}
        disabled={filterBusy}
        class="flex flex-wrap"
      >
        {#each CRAWLER_ACTIVE_INVENTORY_LIFECYCLE_FILTER_OPTIONS as option (option)}
          <ToggleGroup.Item value={option}>
            {getCrawlerActiveInventoryLifecycleFilterLabel(option)}
          </ToggleGroup.Item>
        {/each}
      </ToggleGroup.Root>
      <Input
        type="search"
        class="w-full sm:w-64"
        bind:value={search}
        placeholder={m.crawler_active_inventory_search_placeholder()}
        aria-label={m.crawler_active_inventory_search_label()}
      />
    </div>
  </Card.Header>
  <Card.Content class="pt-0">
    {#if loadFailed}
      <Alert.Root variant="destructive">
        <TriangleAlert aria-hidden="true" />
        <Alert.Description>{m.crawler_active_inventory_load_error()}</Alert.Description>
      </Alert.Root>
    {:else if filterBusy}
      <p class="text-muted-foreground text-sm">
        {m.crawler_active_inventory_filter_busy()}
      </p>
    {:else if !activeInventory || activeInventory.items.length === 0}
      <EmptyState
        title={m.crawler_empty_active_inventory_title()}
        description={m.crawler_empty_active_inventory_description()}
      >
        {#snippet icon()}
          <Inbox class="size-5" />
        {/snippet}
      </EmptyState>
    {:else if visibleItems.length === 0}
      <EmptyState
        title={m.crawler_empty_websites_filtered_title()}
        description={m.crawler_active_inventory_search_empty()}
      >
        {#snippet icon()}
          <ListChecks class="size-5" />
        {/snippet}
      </EmptyState>
    {:else}
      <div class="overflow-x-auto">
        <Table.Root class="min-w-[56rem]">
          <Table.Caption class="sr-only">
            {m.crawler_active_inventory_table_caption()}
          </Table.Caption>
          <Table.Header>
            <Table.Row>
              <Table.Head>{m.crawler_active_inventory_column_website()}</Table.Head>
              <Table.Head>{m.crawler_active_inventory_column_source()}</Table.Head>
              <Table.Head>{m.crawler_active_inventory_column_started_by()}</Table.Head>
              <Table.Head>{m.crawler_active_inventory_column_status()}</Table.Head>
              <Table.Head>{m.crawler_active_inventory_column_activity()}</Table.Head>
              <Table.Head class="text-right">
                {m.crawler_active_inventory_column_updated()}
              </Table.Head>
              <Table.Head class="text-right">
                {m.crawler_active_inventory_column_action()}
              </Table.Head>
            </Table.Row>
          </Table.Header>
          <Table.Body>
            {#each visibleItems as activeItem (activeItem.job_id)}
              {@const sourceLabel = getCrawlerActiveInventorySourceLabel(activeItem)}
              {@const startedByLabel = getCrawlerActiveInventoryStartedByLabel(activeItem)}
              {@const activeResolved = activeItem.website_id
                ? resolveRowLabel({
                    website_id: activeItem.website_id,
                    website_name: activeItem.website_name
                  })
                : {
                    label: getCrawlerActiveInventoryWebsiteLabel(activeItem),
                    inventoryItem: null
                  }}
              <Table.Row
                class={activeResolved.inventoryItem
                  ? "hover:bg-muted/40 focus-within:bg-muted/40 cursor-pointer"
                  : ""}
                onclick={() =>
                  activeResolved.inventoryItem && onOpenWebsiteDetail(activeResolved.inventoryItem)}
              >
                <Table.Cell class="max-w-64">
                  <span class="block truncate font-medium" title={activeResolved.label}>
                    {activeResolved.label}
                  </span>
                </Table.Cell>
                <Table.Cell class="text-muted-foreground max-w-56 truncate text-sm">
                  {#if sourceLabel}
                    <span class="block truncate" title={sourceLabel}>{sourceLabel}</span>
                  {:else}
                    <span class="text-muted-foreground/60 text-xs">
                      {m.crawler_active_inventory_source_unknown()}
                    </span>
                  {/if}
                </Table.Cell>
                <Table.Cell class="text-muted-foreground max-w-56 truncate text-sm">
                  {#if startedByLabel}
                    <span class="block truncate" title={startedByLabel}>
                      {startedByLabel}
                    </span>
                  {:else}
                    <span class="text-muted-foreground/60 text-xs">
                      {m.crawler_active_inventory_started_by_unknown()}
                    </span>
                  {/if}
                </Table.Cell>
                <Table.Cell>
                  <Badge
                    variant="outline"
                    class={crawlerActiveStatusBadgeClass(activeItem.lifecycle_state)}
                  >
                    {getCrawlerActiveInventoryStatusLabel(activeItem)}
                  </Badge>
                </Table.Cell>
                <Table.Cell class="whitespace-normal">
                  <div class="flex flex-wrap gap-1.5">
                    {#each getCrawlerActiveInventoryResultLabels(activeItem) as label (label.label)}
                      <Badge
                        variant="outline"
                        class={crawlerResultBadgeClass(label.color)}
                        title={label.tooltip}
                      >
                        {label.label}
                      </Badge>
                    {/each}
                  </div>
                </Table.Cell>
                <Table.Cell class="text-muted-foreground text-right text-xs tabular-nums">
                  {formatCrawlerDateTime(activeItem.job_updated_at)}
                </Table.Cell>
                <Table.Cell class="text-right" onclick={(event) => event.stopPropagation()}>
                  <div class="flex flex-wrap items-center justify-end gap-2">
                    {#if activeItem.update_interval !== null && activeItem.website_id !== null}
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={savingIntervalWebsiteId !== null}
                        aria-label={m.crawler_update_interval_button_aria({
                          website: getCrawlerActiveInventoryWebsiteLabel(activeItem)
                        })}
                        onclick={() => onOpenIntervalDialog(activeItem)}
                      >
                        {savingIntervalWebsiteId === activeItem.website_id
                          ? m.crawler_update_interval_dialog_busy()
                          : m.crawler_update_interval_button()}
                      </Button>
                    {/if}
                    {#if canAbortCrawlerActiveInventoryItem(activeItem)}
                      {@const ariaLabel = isCrawlerActiveInventoryItemRunning(activeItem)
                        ? m.crawler_abort_button_aria_running({
                            website: getCrawlerActiveInventoryWebsiteLabel(activeItem)
                          })
                        : m.crawler_abort_button_aria_queued({
                            website: getCrawlerActiveInventoryWebsiteLabel(activeItem)
                          })}
                      <Button
                        variant="destructive"
                        size="sm"
                        disabled={abortingJobId !== null}
                        aria-label={ariaLabel}
                        onclick={() => onOpenAbortDialog(activeItem)}
                      >
                        <CircleX data-icon="inline-start" aria-hidden="true" />
                        {abortingJobId === activeItem.job_id
                          ? m.crawler_abort_button_busy()
                          : m.crawler_abort_button()}
                      </Button>
                    {/if}
                    {#if !canAbortCrawlerActiveInventoryItem(activeItem) && (activeItem.update_interval === null || activeItem.website_id === null)}
                      <span class="text-muted-foreground text-xs" aria-hidden="true">—</span>
                    {/if}
                  </div>
                </Table.Cell>
              </Table.Row>
            {/each}
          </Table.Body>
        </Table.Root>
      </div>
      {#if activeInventory.total > pageSize}
        <div class="mt-4 flex flex-wrap items-center justify-between gap-3">
          <div class="flex items-center gap-2">
            <label
              for="crawler-active-page-size"
              class="text-muted-foreground text-xs tracking-wide uppercase"
            >
              {m.crawler_active_inventory_page_size_label()}
            </label>
            <Select.Root
              type="single"
              value={String(pageSize)}
              onValueChange={(value) => {
                if (value) onPageSizeChange(value);
              }}
              disabled={filterBusy}
            >
              <Select.Trigger
                id="crawler-active-page-size"
                class="w-20"
                aria-label={m.crawler_active_inventory_page_size_label()}
              >
                {pageSize}
              </Select.Trigger>
              <Select.Content>
                {#each CRAWLER_ACTIVE_INVENTORY_PAGE_SIZES as option (option)}
                  <Select.Item value={String(option)}>{option}</Select.Item>
                {/each}
              </Select.Content>
            </Select.Root>
          </div>
          <Pagination.Root
            count={activeInventory.total}
            perPage={pageSize}
            {page}
            onPageChange={(next) => {
              if (next === page || filterBusy || next < 1) return;
              onRefresh({ page: next });
            }}
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
    {/if}
  </Card.Content>
</Card.Root>
