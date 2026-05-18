<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).
    See the LICENSE file at the repository root for the full license text.
-->

<script lang="ts">
  import { fly } from "svelte/transition";
  import { quintOut } from "svelte/easing";
  import type { SvelteSet } from "svelte/reactivity";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Pagination from "$lib/components/ui/pagination/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import {
    CircleX,
    Clock,
    Eye,
    FileSearch,
    Globe,
    ListChecks,
    MoreVertical,
    Play,
    RefreshCcw,
    Trash2,
    TriangleAlert
  } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import { CRAWLER_BULK_INTERVAL_MAX_WEBSITE_IDS } from "$lib/features/admin/crawlerBulkInterval";
  import { formatCrawlerScheduledIndexedSize } from "$lib/features/admin/crawlerScheduledAggregate";
  import {
    CRAWLER_TENANT_WEBSITE_INVENTORY_PAGE_SIZES,
    getCrawlerTenantWebsiteInventoryDisplayName,
    getCrawlerTenantWebsiteInventoryOwnerLabel,
    getCrawlerTenantWebsiteInventorySpaceLabel,
    getCrawlerTenantWebsiteInventoryStatusLabel,
    type CrawlerTenantWebsiteInventoryItem,
    type CrawlerTenantWebsiteInventoryPageSize,
    type CrawlerTenantWebsiteInventoryResponse,
    type CrawlerTenantWebsiteInventoryStateFilter
  } from "$lib/features/admin/crawlerTenantWebsiteInventory";
  import {
    CRAWLER_UPDATE_INTERVAL_OPTIONS,
    getCrawlerUpdateIntervalLabel,
    type CrawlerUpdateInterval
  } from "$lib/features/admin/crawlerUpdateInterval";
  import EmptyState from "./EmptyState.svelte";

  type StateFilterValue = CrawlerTenantWebsiteInventoryStateFilter;
  type FilterStateOption = { value: StateFilterValue; label: string; dot: string | null };

  type RefreshOptions = {
    interval?: CrawlerUpdateInterval | "";
    state?: StateFilterValue;
    resetPage?: boolean;
    page?: number;
  };

  type InventoryState = {
    visible: CrawlerTenantWebsiteInventoryResponse | null;
    override: CrawlerTenantWebsiteInventoryResponse | null;
    busy: boolean;
    loadFailed: boolean;
    page: number;
    pageSize: CrawlerTenantWebsiteInventoryPageSize;
  };

  type FiltersState = {
    intervalFilter: CrawlerUpdateInterval | "";
    stateFilter: StateFilterValue;
    stateFilterOptions: readonly FilterStateOption[];
    activeFilterCount: () => number;
  };

  type SelectionState = {
    ids: SvelteSet<string>;
    allVisibleSelected: () => boolean;
    someVisibleSelected: () => boolean;
    offPageCount: number;
  };

  type MutationState = {
    retryingWebsiteId: string | null;
    savingIntervalWebsiteId: string | null;
    resettingCircuitWebsiteId: string | null;
    deletingWebsiteId: string | null;
  };

  type RowDialogCallbacks = {
    onOpenWebsiteDetail: (item: CrawlerTenantWebsiteInventoryItem) => void;
    onAdaptRetryDialog: (item: CrawlerTenantWebsiteInventoryItem) => void;
    onAdaptIntervalDialog: (item: CrawlerTenantWebsiteInventoryItem) => void;
    onAdaptCircuitResetDialog: (item: CrawlerTenantWebsiteInventoryItem) => void;
    onOpenDeleteDialog: (item: CrawlerTenantWebsiteInventoryItem) => void;
  };

  type Props = {
    inventory: InventoryState;
    filters: FiltersState;
    selection: SelectionState;
    mutationState: MutationState;
    rowDialogs: RowDialogCallbacks;
    rowStatusClass: (item: CrawlerTenantWebsiteInventoryItem) => string;
    formatLastCrawled: (value: string | null) => string;
    search: string;
    onSearchInput: (value: string) => void;
    onClearSearch: () => void;
    onClearFilters: () => void;
    onRefresh: (options: RefreshOptions) => void;
    onChangePageSize: (value: string) => void;
    onToggleRowSelection: (websiteId: string, value: boolean) => void;
    onToggleSelectAllVisible: (value: boolean) => void;
    onClearSelection: () => void;
    onOpenBulkIntervalDialog: () => void;
  };

  let {
    inventory,
    filters,
    selection,
    mutationState,
    rowDialogs,
    rowStatusClass,
    formatLastCrawled,
    search = $bindable(),
    onSearchInput,
    onClearSearch,
    onClearFilters,
    onRefresh,
    onChangePageSize,
    onToggleRowSelection,
    onToggleSelectAllVisible,
    onClearSelection,
    onOpenBulkIntervalDialog
  }: Props = $props();
</script>

<Card.Root class="mb-14" aria-labelledby="crawler-tenant-website-inventory-title">
  <Card.Header>
    <div class="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
      <div class="flex min-w-0 flex-col gap-1">
        <h2
          id="crawler-tenant-website-inventory-title"
          class="text-base leading-snug font-semibold"
        >
          {m.crawler_tenant_website_inventory_title()}
        </h2>
        <Card.Description>
          {m.crawler_tenant_website_inventory_description()}
        </Card.Description>
      </div>
      {#if inventory.visible}
        <Badge variant="outline" class="shrink-0 tabular-nums">
          {m.crawler_tenant_website_inventory_count({
            shown: inventory.visible.items.length,
            total: inventory.visible.total
          })}
        </Badge>
      {/if}
    </div>
    <div class="bg-subtle border-default mt-4 flex flex-col gap-3 rounded-lg border p-3">
      <div class="flex flex-wrap items-center gap-2">
        <div class="relative min-w-[240px] flex-1">
          <Input
            type="search"
            bind:value={search}
            oninput={(event) => onSearchInput(event.currentTarget.value)}
            placeholder={m.crawler_tenant_website_inventory_search_placeholder()}
            aria-label={m.crawler_tenant_website_inventory_search_label()}
            class="pr-9"
          />
          {#if search.length > 0}
            <button
              type="button"
              class="text-muted-foreground hover:bg-muted focus-visible:ring-ring/50 absolute top-1/2 right-2 -translate-y-1/2 rounded p-1 transition-colors focus-visible:ring-2 focus-visible:outline-none"
              aria-label={m.crawler_tenant_website_inventory_search_clear()}
              onclick={onClearSearch}
            >
              <CircleX class="size-4" aria-hidden="true" />
            </button>
          {/if}
        </div>
        {#if filters.activeFilterCount() > 0}
          <Button variant="ghost" size="sm" onclick={onClearFilters}>
            {m.crawler_tenant_website_inventory_clear_filters()}
          </Button>
        {/if}
      </div>

      <div class="flex flex-col gap-1.5">
        <span class="text-muted-foreground text-[10px] font-medium tracking-wide uppercase">
          {m.crawler_filter_group_interval()}
        </span>
        <div
          role="group"
          aria-label={m.crawler_tenant_website_inventory_interval_filter_label()}
          class="flex flex-wrap gap-1.5"
        >
          <button
            type="button"
            aria-pressed={filters.intervalFilter === ""}
            onclick={() => onRefresh({ interval: "", resetPage: true })}
            class={filters.intervalFilter === ""
              ? "border-accent-default bg-accent-default/10 text-accent-default ring-accent-default/20 inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium ring-2 transition-all"
              : "border-border bg-background text-muted-foreground hover:border-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-all"}
          >
            {m.crawler_tenant_website_inventory_interval_filter_all()}
          </button>
          {#each CRAWLER_UPDATE_INTERVAL_OPTIONS as interval (interval)}
            {@const isActive = filters.intervalFilter === interval}
            <button
              type="button"
              aria-pressed={isActive}
              onclick={() => onRefresh({ interval, resetPage: true })}
              class={isActive
                ? "border-accent-default bg-accent-default/10 text-accent-default ring-accent-default/20 inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium ring-2 transition-all"
                : "border-border bg-background text-muted-foreground hover:border-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-all"}
            >
              {getCrawlerUpdateIntervalLabel(interval)}
            </button>
          {/each}
        </div>
      </div>

      <div class="flex flex-col gap-1.5">
        <span class="text-muted-foreground text-[10px] font-medium tracking-wide uppercase">
          {m.crawler_filter_group_status()}
        </span>
        <div
          role="group"
          aria-label={m.crawler_tenant_website_inventory_state_filter_label()}
          class="flex flex-wrap gap-1.5"
        >
          {#each filters.stateFilterOptions as option (option.value)}
            {@const isActive = filters.stateFilter === option.value}
            <button
              type="button"
              aria-pressed={isActive}
              onclick={() => onRefresh({ state: option.value, resetPage: true })}
              class={isActive
                ? "border-accent-default bg-accent-default/10 text-accent-default ring-accent-default/20 inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium ring-2 transition-all"
                : "border-border bg-background text-muted-foreground hover:border-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-all"}
            >
              {#if option.dot}
                <span class="size-2 rounded-full {option.dot}" aria-hidden="true"></span>
              {/if}
              {option.label}
            </button>
          {/each}
        </div>
      </div>
    </div>
  </Card.Header>
  <Card.Content class="pt-0">
    {#if inventory.loadFailed && !inventory.override}
      <Alert.Root variant="destructive">
        <TriangleAlert aria-hidden="true" />
        <Alert.Description>
          {m.crawler_tenant_website_inventory_load_error()}
        </Alert.Description>
      </Alert.Root>
    {:else if inventory.busy && !inventory.visible}
      <p class="text-muted-foreground text-sm">
        {m.crawler_tenant_website_inventory_loading()}
      </p>
    {:else if !inventory.visible || inventory.visible.items.length === 0}
      {#if filters.activeFilterCount() > 0}
        <EmptyState
          title={m.crawler_empty_websites_filtered_title()}
          description={m.crawler_empty_websites_filtered_description()}
        >
          {#snippet icon()}
            <ListChecks class="size-5" />
          {/snippet}
          {#snippet actions()}
            <Button variant="ghost" size="sm" onclick={onClearFilters}>
              {m.crawler_tenant_website_inventory_clear_filters()}
            </Button>
          {/snippet}
        </EmptyState>
      {:else}
        <EmptyState
          title={m.crawler_empty_websites_title()}
          description={m.crawler_empty_websites_description()}
        >
          {#snippet icon()}
            <Globe class="size-5" />
          {/snippet}
        </EmptyState>
      {/if}
    {:else}
      {#if selection.ids.size > 0}
        {@const selectionOverCap = selection.ids.size > CRAWLER_BULK_INTERVAL_MAX_WEBSITE_IDS}
        <div
          in:fly={{ y: -8, duration: 180, easing: quintOut }}
          out:fly={{ y: -4, duration: 120, easing: quintOut }}
          class="border-border bg-muted/40 mb-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border px-4 py-2.5"
          role="region"
          aria-label={m.crawler_bulk_interval_toolbar_apply()}
        >
          <div class="flex flex-col gap-1">
            <span class="text-foreground text-sm font-medium tabular-nums">
              {selection.ids.size === 1
                ? m.crawler_bulk_interval_toolbar_count_one()
                : m.crawler_bulk_interval_toolbar_count_other({
                    count: String(selection.ids.size)
                  })}
            </span>
            {#if selection.offPageCount > 0}
              <span class="text-muted-foreground text-xs">
                {m.crawler_bulk_interval_offpage_hint({
                  count: String(selection.offPageCount)
                })}
              </span>
            {/if}
            {#if selectionOverCap}
              <span class="text-caution text-xs">
                {m.crawler_bulk_interval_toolbar_cap_warning({
                  limit: String(CRAWLER_BULK_INTERVAL_MAX_WEBSITE_IDS)
                })}
              </span>
            {/if}
          </div>
          <div class="flex items-center gap-2">
            <Button variant="ghost" size="sm" onclick={onClearSelection}>
              {m.crawler_bulk_interval_toolbar_clear()}
            </Button>
            <Button
              variant="default"
              size="sm"
              disabled={selectionOverCap}
              onclick={onOpenBulkIntervalDialog}
            >
              {m.crawler_bulk_interval_toolbar_apply()}
            </Button>
          </div>
        </div>
      {/if}
      <div class="overflow-x-auto">
        <Table.Root class="min-w-[58rem]">
          <Table.Caption class="sr-only">
            {m.crawler_tenant_website_inventory_table_caption()}
          </Table.Caption>
          <Table.Header>
            <Table.Row>
              <Table.Head class="w-10">
                <span class="sr-only">
                  {m.crawler_tenant_website_inventory_column_select()}
                </span>
                <Checkbox
                  checked={selection.allVisibleSelected()}
                  indeterminate={!selection.allVisibleSelected() && selection.someVisibleSelected()}
                  onCheckedChange={(value) => onToggleSelectAllVisible(value === true)}
                  aria-label={m.crawler_tenant_website_inventory_select_all_label()}
                />
              </Table.Head>
              <Table.Head>{m.crawler_tenant_website_inventory_column_website()}</Table.Head>
              <Table.Head>{m.crawler_tenant_website_inventory_column_owner()}</Table.Head>
              <Table.Head>{m.crawler_tenant_website_inventory_column_space()}</Table.Head>
              <Table.Head>{m.crawler_tenant_website_inventory_column_schedule()}</Table.Head>
              <Table.Head class="text-right">
                {m.crawler_tenant_website_inventory_column_last_crawled()}
              </Table.Head>
              <Table.Head>{m.crawler_tenant_website_inventory_column_status()}</Table.Head>
              <Table.Head class="text-right">
                {m.crawler_tenant_website_inventory_column_size()}
              </Table.Head>
              <Table.Head class="w-12 text-right">
                <span class="sr-only">{m.crawler_inventory_row_column_actions()}</span>
              </Table.Head>
            </Table.Row>
          </Table.Header>
          <Table.Body>
            {#each inventory.visible.items as websiteItem (websiteItem.website_id)}
              {@const displayName = getCrawlerTenantWebsiteInventoryDisplayName(websiteItem)}
              {@const isSelected = selection.ids.has(websiteItem.website_id)}
              <Table.Row
                class={isSelected
                  ? "bg-accent-default/8 hover:bg-accent-default/12 focus-within:bg-accent-default/12 cursor-pointer"
                  : "hover:bg-muted/40 focus-within:bg-muted/40 cursor-pointer"}
                onclick={() => rowDialogs.onOpenWebsiteDetail(websiteItem)}
              >
                <Table.Cell class="w-10">
                  <span
                    class="inline-flex items-center"
                    onclick={(event) => event.stopPropagation()}
                    role="presentation"
                  >
                    <Checkbox
                      checked={isSelected}
                      onCheckedChange={(value) =>
                        onToggleRowSelection(websiteItem.website_id, value === true)}
                      aria-label={m.crawler_tenant_website_inventory_row_checkbox_label()}
                    />
                  </span>
                </Table.Cell>
                <Table.Cell class="max-w-64">
                  <span class="block truncate font-medium" title={displayName}>
                    {displayName}
                  </span>
                  {#if websiteItem.url && websiteItem.url !== displayName}
                    <span
                      class="text-muted-foreground block truncate text-xs"
                      title={websiteItem.url}
                    >
                      {websiteItem.url}
                    </span>
                  {/if}
                </Table.Cell>
                <Table.Cell class="text-muted-foreground max-w-56 truncate text-sm">
                  {#if websiteItem.owner_email}
                    <!-- eslint-disable svelte/no-navigation-without-resolve -- localizeHref handles routing -->
                    <a
                      href={localizeHref(
                        `/admin/users?tab=active&search=${encodeURIComponent(websiteItem.owner_email)}`
                      )}
                      onclick={(event) => event.stopPropagation()}
                      class="hover:text-foreground block truncate hover:underline"
                      title={websiteItem.owner_email}
                    >
                      {websiteItem.owner_email}
                    </a>
                    <!-- eslint-enable svelte/no-navigation-without-resolve -->
                  {:else}
                    <span
                      class="block truncate"
                      title={getCrawlerTenantWebsiteInventoryOwnerLabel(websiteItem)}
                    >
                      {getCrawlerTenantWebsiteInventoryOwnerLabel(websiteItem)}
                    </span>
                  {/if}
                </Table.Cell>
                <Table.Cell class="text-muted-foreground max-w-56 truncate text-sm">
                  <span
                    class="block truncate"
                    title={getCrawlerTenantWebsiteInventorySpaceLabel(websiteItem)}
                  >
                    {getCrawlerTenantWebsiteInventorySpaceLabel(websiteItem)}
                  </span>
                </Table.Cell>
                <Table.Cell class="text-sm">
                  {getCrawlerUpdateIntervalLabel(websiteItem.update_interval)}
                </Table.Cell>
                <Table.Cell class="text-muted-foreground text-right text-xs tabular-nums">
                  {formatLastCrawled(websiteItem.last_crawled_at)}
                </Table.Cell>
                <Table.Cell>
                  <Badge variant="outline" class={rowStatusClass(websiteItem)}>
                    {getCrawlerTenantWebsiteInventoryStatusLabel(websiteItem)}
                  </Badge>
                </Table.Cell>
                <Table.Cell class="text-right text-sm tabular-nums">
                  {websiteItem.size > 0 ? formatCrawlerScheduledIndexedSize(websiteItem.size) : "—"}
                </Table.Cell>
                <Table.Cell class="w-12 text-right" onclick={(event) => event.stopPropagation()}>
                  <DropdownMenu.Root>
                    <DropdownMenu.Trigger>
                      {#snippet child({ props })}
                        <Button
                          {...props}
                          variant="ghost"
                          size="icon"
                          class="size-8"
                          aria-label={m.crawler_inventory_row_actions_aria({
                            website: getCrawlerTenantWebsiteInventoryDisplayName(websiteItem)
                          })}
                        >
                          <MoreVertical class="size-4" />
                        </Button>
                      {/snippet}
                    </DropdownMenu.Trigger>
                    <DropdownMenu.Content align="end" class="min-w-56">
                      <DropdownMenu.Item
                        onclick={() => rowDialogs.onOpenWebsiteDetail(websiteItem)}
                      >
                        <Eye class="size-4" />
                        {m.crawler_inventory_row_action_view_detail()}
                      </DropdownMenu.Item>
                      {#if websiteItem.url}
                        <!-- eslint-disable svelte/no-navigation-without-resolve -- external website URL -->
                        <DropdownMenu.Item>
                          {#snippet child({ props })}
                            <a
                              {...props}
                              href={websiteItem.url}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              <Globe class="size-4" />
                              {m.crawler_inventory_row_action_open_external()}
                            </a>
                          {/snippet}
                        </DropdownMenu.Item>
                        <!-- eslint-enable svelte/no-navigation-without-resolve -->
                      {/if}
                      <DropdownMenu.Separator />
                      <DropdownMenu.Item
                        onclick={() => rowDialogs.onAdaptRetryDialog(websiteItem)}
                        disabled={mutationState.retryingWebsiteId !== null}
                      >
                        <Play class="size-4" />
                        {m.crawler_website_detail_action_retry()}
                      </DropdownMenu.Item>
                      <DropdownMenu.Item
                        onclick={() => rowDialogs.onAdaptIntervalDialog(websiteItem)}
                        disabled={mutationState.savingIntervalWebsiteId !== null}
                      >
                        <Clock class="size-4" />
                        {m.crawler_website_detail_action_interval()}
                      </DropdownMenu.Item>
                      {#if websiteItem.failure_state !== null}
                        <DropdownMenu.Item
                          onclick={() => rowDialogs.onAdaptCircuitResetDialog(websiteItem)}
                          disabled={mutationState.resettingCircuitWebsiteId !== null}
                        >
                          <RefreshCcw class="size-4" />
                          {m.crawler_website_detail_action_reset()}
                        </DropdownMenu.Item>
                      {/if}
                      <DropdownMenu.Separator />
                      <!-- eslint-disable svelte/no-navigation-without-resolve -- localizeHref handles routing -->
                      <DropdownMenu.Item>
                        {#snippet child({ props })}
                          <a
                            {...props}
                            href={localizeHref(
                              `/admin/audit-logs?tab=logs&search=${encodeURIComponent(
                                websiteItem.url
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
                        onclick={() => rowDialogs.onOpenDeleteDialog(websiteItem)}
                        disabled={mutationState.deletingWebsiteId !== null}
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
      {#if inventory.visible.total > inventory.pageSize}
        <div class="mt-4 flex flex-wrap items-center justify-between gap-3">
          <div class="flex items-center gap-2">
            <label
              for="crawler-websites-page-size"
              class="text-muted-foreground text-xs tracking-wide uppercase"
            >
              {m.crawler_active_inventory_page_size_label()}
            </label>
            <Select.Root
              type="single"
              value={String(inventory.pageSize)}
              onValueChange={(value) => {
                if (value) onChangePageSize(value);
              }}
              disabled={inventory.busy}
            >
              <Select.Trigger
                id="crawler-websites-page-size"
                class="w-20"
                aria-label={m.crawler_active_inventory_page_size_label()}
              >
                {inventory.pageSize}
              </Select.Trigger>
              <Select.Content>
                {#each CRAWLER_TENANT_WEBSITE_INVENTORY_PAGE_SIZES as option (option)}
                  <Select.Item value={String(option)}>{option}</Select.Item>
                {/each}
              </Select.Content>
            </Select.Root>
          </div>
          <Pagination.Root
            count={inventory.visible.total}
            perPage={inventory.pageSize}
            page={inventory.page}
            onPageChange={(next) => {
              if (next === inventory.page || inventory.busy || next < 1) return;
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
