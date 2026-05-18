<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).
    See the LICENSE file at the repository root for the full license text.
-->

<script lang="ts">
  import { invalidate } from "$app/navigation";
  import { onMount, untrack } from "svelte";
  import { SvelteSet } from "svelte/reactivity";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Tabs from "$lib/components/ui/tabs/index.js";
  import AktivitetTab from "./AktivitetTab.svelte";
  import BulkIntervalDialog from "./BulkIntervalDialog.svelte";
  import CrawlerAdminDialogs from "./CrawlerAdminDialogs.svelte";
  import DriftTab from "./DriftTab.svelte";
  import HälsaTab from "./HälsaTab.svelte";
  import InställningarTab from "./InställningarTab.svelte";
  import KpiSummary from "./KpiSummary.svelte";
  import WebbplatserTab from "./WebbplatserTab.svelte";
  import WebsiteDetailDialog from "./WebsiteDetailDialog.svelte";
  import { createCrawlerActivityState } from "./crawlerActivityState.svelte";
  import {
    createBulkIntervalState,
    createCrawlerDialogState
  } from "./crawlerAdminPageState.svelte";
  import { Page } from "$lib/components/layout";
  import { getIntric } from "$lib/core/Intric.js";
  import { toastError } from "$lib/core/errors";
  import type { CrawlerSettings } from "$lib/features/admin/crawlerSettings";
  import {
    CRAWLER_ACTIVE_INVENTORY_DEFAULTS,
    isCrawlerActiveInventoryPageSize,
    offsetFromCrawlerActiveInventoryPage,
    type CrawlerActiveInventoryLifecycleFilter,
    type CrawlerActiveInventoryPageSize,
    type CrawlerActiveInventoryResponse
  } from "$lib/features/admin/crawlerActiveInventory";
  import type { CrawlerTenantFailureInventoryResponse } from "$lib/features/admin/crawlerFailureInventory";
  import type { CrawlerUpdateInterval } from "$lib/features/admin/crawlerUpdateInterval";
  import { formatCrawlerDateTime } from "$lib/features/admin/crawlerPresentation";
  import {
    CRAWLER_RECENT_FAILURES_PAGE_SIZE,
    offsetFromCrawlerRecentFailuresPage,
    type CrawlerRecentFailuresResponse
  } from "$lib/features/admin/crawlerRecentFailures";
  import {
    CRAWLER_WATCHDOG_INTERVENTIONS_PAGE_SIZE,
    offsetFromCrawlerWatchdogInterventionsPage,
    type CrawlerWatchdogInterventionsResponse
  } from "$lib/features/admin/crawlerWatchdogInterventions";
  import type { CrawlerScheduledAggregateResponse } from "$lib/features/admin/crawlerScheduledAggregate";
  import type { CrawlerTenantWebsiteProcessingAggregateResponse } from "$lib/features/admin/crawlerWebsiteProcessing";
  import {
    CRAWLER_TENANT_WEBSITE_INVENTORY_DEFAULTS,
    isCrawlerTenantWebsiteInventoryPageSize,
    offsetFromCrawlerTenantWebsiteInventoryPage,
    type CrawlerFailureState,
    type CrawlerTenantWebsiteInventoryItem,
    type CrawlerTenantWebsiteInventoryPageSize,
    type CrawlerTenantWebsiteInventoryResponse,
    type CrawlerTenantWebsiteInventorySort
  } from "$lib/features/admin/crawlerTenantWebsiteInventory";
  import { m } from "$lib/paraglide/messages";

  const intric = getIntric();
  let {
    data
  }: {
    data: {
      crawlerSettings: CrawlerSettings;
      crawlerActiveInventory: CrawlerActiveInventoryResponse | null;
      crawlerActiveInventoryLoadFailed: boolean;
      crawlerFailureInventory: CrawlerTenantFailureInventoryResponse | null;
      crawlerFailureInventoryLoadFailed: boolean;
      crawlerRecentFailuresWindowDays: number;
      crawlerRecentFailures: CrawlerRecentFailuresResponse | null;
      crawlerRecentFailuresLoadFailed: boolean;
      crawlerWatchdogInterventionsWindowDays: number;
      crawlerWatchdogInterventions: CrawlerWatchdogInterventionsResponse | null;
      crawlerWatchdogInterventionsLoadFailed: boolean;
      crawlerScheduledAggregate: CrawlerScheduledAggregateResponse | null;
      crawlerScheduledAggregateLoadFailed: boolean;
      crawlerWebsiteProcessingWindowDays: number;
      crawlerWebsiteProcessing: CrawlerTenantWebsiteProcessingAggregateResponse | null;
      crawlerWebsiteProcessingLoadFailed: boolean;
      crawlerTenantWebsiteInventory: CrawlerTenantWebsiteInventoryResponse | null;
      crawlerTenantWebsiteInventoryLoadFailed: boolean;
    };
  } = $props();

  let detailCandidate = $state<CrawlerTenantWebsiteInventoryItem | null>(null);
  const dialogs = createCrawlerDialogState(intric, {
    set: (item) => (detailCandidate = item)
  });

  // The activity state owns subsequent refetches (filters / sort / page);
  // it only needs the SSR snapshot at construction. `untrack` silences
  // the Svelte 5 "state-only-captures-initial-value" warning, which is
  // exactly the semantics we want here — later page-load refreshes go
  // through `intric` from inside the state module, not through `data`.
  const activity = untrack(() =>
    createCrawlerActivityState(intric, {
      response: data.crawlerWebsiteProcessing ?? null,
      loadFailed: data.crawlerWebsiteProcessingLoadFailed
    })
  );

  let activeInventoryLifecycleFilter = $state<CrawlerActiveInventoryLifecycleFilter>("all");
  let activeInventoryFiltered = $state<CrawlerActiveInventoryResponse | null>(null);
  let activeInventoryFilterBusy = $state(false);
  const visibleActiveInventory = $derived(activeInventoryFiltered ?? data.crawlerActiveInventory);
  let activeInventoryPageSize = $state<CrawlerActiveInventoryPageSize>(
    CRAWLER_ACTIVE_INVENTORY_DEFAULTS.limit
  );
  let activeInventoryPage = $state<number>(1);

  let activeInventorySearch = $state<string>("");
  const activeInventorySearchNormalized = $derived(activeInventorySearch.trim().toLowerCase());
  const visibleActiveInventoryItems = $derived(
    visibleActiveInventory && activeInventorySearchNormalized
      ? visibleActiveInventory.items.filter((item) => {
          const name = item.website_name?.toLowerCase() ?? "";
          return name.includes(activeInventorySearchNormalized);
        })
      : (visibleActiveInventory?.items ?? [])
  );

  let recentFailuresPage = $state<number>(1);
  let recentFailuresOverride = $state<CrawlerRecentFailuresResponse | null>(null);
  let recentFailuresBusy = $state(false);
  const visibleRecentFailures = $derived(recentFailuresOverride ?? data.crawlerRecentFailures);

  let watchdogInterventionsPage = $state<number>(1);
  let watchdogInterventionsOverride = $state<CrawlerWatchdogInterventionsResponse | null>(null);
  let watchdogInterventionsBusy = $state(false);
  const visibleWatchdogInterventions = $derived(
    watchdogInterventionsOverride ?? data.crawlerWatchdogInterventions
  );

  type CrawlerAdminTab = "operations" | "websites" | "health" | "activity" | "settings";
  let currentTab = $state<CrawlerAdminTab>("operations");

  let tenantWebsiteInventoryPage = $state<number>(1);
  let tenantWebsiteInventoryPageSize = $state<CrawlerTenantWebsiteInventoryPageSize>(
    CRAWLER_TENANT_WEBSITE_INVENTORY_DEFAULTS.limit
  );
  let tenantWebsiteInventorySort = $state<CrawlerTenantWebsiteInventorySort>(
    CRAWLER_TENANT_WEBSITE_INVENTORY_DEFAULTS.sort
  );
  let tenantWebsiteInventorySearch = $state<string>("");
  let tenantWebsiteInventoryIntervalFilter = $state<CrawlerUpdateInterval | "">("");
  let tenantWebsiteInventoryStateFilter = $state<CrawlerFailureState | "all" | "healthy">("all");
  let tenantWebsiteInventoryOverride = $state<CrawlerTenantWebsiteInventoryResponse | null>(null);
  let tenantWebsiteInventoryBusy = $state<boolean>(false);
  let tenantWebsiteInventorySearchDebounceTimer: ReturnType<typeof setTimeout> | null = null;

  const tenantWebsiteInventorySelection = new SvelteSet<string>();
  const bulkInterval = createBulkIntervalState(intric, {
    values: () => tenantWebsiteInventorySelection.values(),
    size: () => tenantWebsiteInventorySelection.size,
    delete: (id) => tenantWebsiteInventorySelection.delete(id)
  });

  // Gate client-side polling on post-hydration; armed inside $effect
  // before onMount can land mid-hydration and mismatch on HMR cycles.
  let pollerPostMount = $state<boolean>(false);
  onMount(() => {
    pollerPostMount = true;
  });

  $effect(() => {
    return () => {
      if (tenantWebsiteInventorySearchDebounceTimer !== null) {
        clearTimeout(tenantWebsiteInventorySearchDebounceTimer);
        tenantWebsiteInventorySearchDebounceTimer = null;
      }
    };
  });

  const visibleTenantWebsiteInventory = $derived(
    tenantWebsiteInventoryOverride ?? data.crawlerTenantWebsiteInventory
  );
  const visibleTenantWebsiteInventoryById = $derived(
    new Map((visibleTenantWebsiteInventory?.items ?? []).map((item) => [item.website_id, item]))
  );

  const tenantWebsiteInventoryMatchesSsrQuery = $derived(
    tenantWebsiteInventoryPage === 1 &&
      tenantWebsiteInventoryPageSize === CRAWLER_TENANT_WEBSITE_INVENTORY_DEFAULTS.limit &&
      tenantWebsiteInventorySort === CRAWLER_TENANT_WEBSITE_INVENTORY_DEFAULTS.sort &&
      tenantWebsiteInventorySearch === "" &&
      tenantWebsiteInventoryIntervalFilter === "" &&
      tenantWebsiteInventoryStateFilter === "all" &&
      !tenantWebsiteInventoryBusy
  );

  function resolveHälsaRowLabel(row: { website_id: string; website_name: string | null }): {
    label: string;
    inventoryItem: CrawlerTenantWebsiteInventoryItem | null;
  } {
    const inventoryItem = visibleTenantWebsiteInventoryById.get(row.website_id) ?? null;
    const label =
      inventoryItem?.url ||
      inventoryItem?.name ||
      row.website_name ||
      `Webbplats ${row.website_id.slice(0, 8)}`;
    return { label, inventoryItem };
  }

  const tenantWebsiteInventoryVisibleSelectionCount = $derived(
    visibleTenantWebsiteInventory
      ? visibleTenantWebsiteInventory.items.reduce(
          (count, item) =>
            tenantWebsiteInventorySelection.has(item.website_id) ? count + 1 : count,
          0
        )
      : 0
  );
  const tenantWebsiteInventoryOffPageSelectionCount = $derived(
    Math.max(0, tenantWebsiteInventorySelection.size - tenantWebsiteInventoryVisibleSelectionCount)
  );

  // Drop the candidate when the SSR payload reference changes (route load /
  // tenant context switch); a stale candidate could expose another tenant.
  let lastSeenSsrInventory: typeof data.crawlerTenantWebsiteInventory = null;
  $effect(() => {
    const current = data.crawlerTenantWebsiteInventory;
    if (lastSeenSsrInventory !== null && current !== lastSeenSsrInventory) {
      detailCandidate = null;
    }
    lastSeenSsrInventory = current;
  });

  // Re-invalidate while the visible query exactly matches the SSR default.
  // Gating on the override alone races with the pre-fetch state mutation in
  // refreshTenantWebsiteInventory; checking individual filter/page state
  // (and busy) keeps polling out of mid-transition snapshots.
  $effect(() => {
    if (!pollerPostMount) return;
    if (currentTab !== "websites") return;
    if (detailCandidate !== null) return;
    if (!tenantWebsiteInventoryMatchesSsrQuery) return;
    const timer = setInterval(() => {
      void invalidate("admin:crawler-tenant-website-inventory");
      void invalidate("admin:crawler-active-inventory");
    }, 60_000);
    return () => clearInterval(timer);
  });

  const tenantWebsiteInventoryStateFilterOptions = $derived<
    {
      value: "all" | "healthy" | CrawlerFailureState;
      label: string;
      dot: string;
    }[]
  >([
    {
      value: "all",
      label: m.crawler_tenant_website_inventory_state_filter_all(),
      dot: ""
    },
    {
      value: "healthy",
      label: m.crawler_tenant_website_inventory_state_healthy(),
      dot: "bg-positive-default"
    },
    {
      value: "BACKED_OFF",
      label: m.crawler_failure_inventory_state_backed_off(),
      dot: "bg-caution"
    },
    {
      value: "AUTO_DISABLED",
      label: m.crawler_failure_inventory_state_paused(),
      dot: "bg-destructive"
    }
  ]);

  async function refreshActiveInventory(opts: {
    filter?: CrawlerActiveInventoryLifecycleFilter;
    page?: number;
    pageSize?: CrawlerActiveInventoryPageSize;
  }) {
    const nextFilter = opts.filter ?? activeInventoryLifecycleFilter;
    const nextPageSize = opts.pageSize ?? activeInventoryPageSize;
    const nextPage = opts.page ?? activeInventoryPage;

    const resetPage = opts.filter !== undefined && opts.filter !== activeInventoryLifecycleFilter;
    const effectivePage = resetPage ? 1 : nextPage;

    activeInventoryLifecycleFilter = nextFilter;
    activeInventoryPage = effectivePage;
    activeInventoryPageSize = nextPageSize;

    const matchesSsr =
      nextFilter === "all" &&
      effectivePage === 1 &&
      nextPageSize === CRAWLER_ACTIVE_INVENTORY_DEFAULTS.limit;
    if (matchesSsr) {
      activeInventoryFiltered = null;
      return;
    }

    activeInventoryFilterBusy = true;
    try {
      const response = await intric.crawlerAdmin.activeInventory({
        limit: nextPageSize,
        offset: offsetFromCrawlerActiveInventoryPage(effectivePage, nextPageSize),
        ...(nextFilter === "all" ? {} : { lifecycle_status: nextFilter })
      });
      activeInventoryFiltered = response;
    } catch (error) {
      toastError(error, m.crawler_active_inventory_filter_failed());
    } finally {
      activeInventoryFilterBusy = false;
    }
  }

  function changeActiveInventoryPageSize(value: string) {
    const parsed = Number.parseInt(value, 10);
    if (!Number.isFinite(parsed) || !isCrawlerActiveInventoryPageSize(parsed)) return;
    if (parsed === activeInventoryPageSize) return;
    void refreshActiveInventory({ page: 1, pageSize: parsed });
  }

  async function changeRecentFailuresPage(nextPage: number) {
    if (nextPage === recentFailuresPage || recentFailuresBusy || nextPage < 1) return;
    if (nextPage === 1) {
      recentFailuresOverride = null;
      recentFailuresPage = 1;
      return;
    }
    recentFailuresBusy = true;
    try {
      const response = await intric.crawlerAdmin.recentFailures({
        days: data.crawlerRecentFailuresWindowDays,
        limit: CRAWLER_RECENT_FAILURES_PAGE_SIZE,
        offset: offsetFromCrawlerRecentFailuresPage(nextPage)
      });
      recentFailuresOverride = response;
      recentFailuresPage = nextPage;
    } catch (error) {
      toastError(error, m.crawler_recent_failures_load_error());
    } finally {
      recentFailuresBusy = false;
    }
  }

  async function changeWatchdogInterventionsPage(nextPage: number) {
    if (nextPage === watchdogInterventionsPage || watchdogInterventionsBusy || nextPage < 1) return;
    if (nextPage === 1) {
      watchdogInterventionsOverride = null;
      watchdogInterventionsPage = 1;
      return;
    }
    watchdogInterventionsBusy = true;
    try {
      const response = await intric.crawlerAdmin.watchdogInterventions({
        days: data.crawlerWatchdogInterventionsWindowDays,
        limit: CRAWLER_WATCHDOG_INTERVENTIONS_PAGE_SIZE,
        offset: offsetFromCrawlerWatchdogInterventionsPage(nextPage)
      });
      watchdogInterventionsOverride = response;
      watchdogInterventionsPage = nextPage;
    } catch (error) {
      toastError(error, m.crawler_watchdog_interventions_load_error());
    } finally {
      watchdogInterventionsBusy = false;
    }
  }

  async function refreshTenantWebsiteInventory(
    opts: {
      search?: string;
      page?: number;
      pageSize?: CrawlerTenantWebsiteInventoryPageSize;
      interval?: CrawlerUpdateInterval | "";
      state?: CrawlerFailureState | "all" | "healthy";
      sort?: CrawlerTenantWebsiteInventorySort;
      resetPage?: boolean;
    } = {}
  ) {
    const nextSearch = opts.search ?? tenantWebsiteInventorySearch;
    const nextInterval = opts.interval ?? tenantWebsiteInventoryIntervalFilter;
    const nextState = opts.state ?? tenantWebsiteInventoryStateFilter;
    const nextSort = opts.sort ?? tenantWebsiteInventorySort;
    const nextPageSize = opts.pageSize ?? tenantWebsiteInventoryPageSize;
    const nextPage = opts.resetPage ? 1 : (opts.page ?? tenantWebsiteInventoryPage);

    tenantWebsiteInventorySearch = nextSearch;
    tenantWebsiteInventoryIntervalFilter = nextInterval;
    tenantWebsiteInventoryStateFilter = nextState;
    tenantWebsiteInventorySort = nextSort;
    tenantWebsiteInventoryPageSize = nextPageSize;
    tenantWebsiteInventoryPage = nextPage;

    const matchesSsr =
      nextPage === 1 &&
      nextPageSize === CRAWLER_TENANT_WEBSITE_INVENTORY_DEFAULTS.limit &&
      nextSort === CRAWLER_TENANT_WEBSITE_INVENTORY_DEFAULTS.sort &&
      nextSearch.trim() === "" &&
      nextInterval === "" &&
      nextState === "all";
    if (matchesSsr) {
      tenantWebsiteInventoryOverride = null;
      return;
    }

    tenantWebsiteInventoryBusy = true;
    try {
      const failureStateParam: CrawlerFailureState | undefined =
        nextState === "all" || nextState === "healthy" ? undefined : nextState;
      const response = await intric.crawlerAdmin.tenantWebsiteInventory({
        limit: nextPageSize,
        offset: offsetFromCrawlerTenantWebsiteInventoryPage(nextPage, nextPageSize),
        sort: nextSort,
        ...(nextSearch.trim() ? { search: nextSearch.trim() } : {}),
        ...(nextInterval ? { update_interval: nextInterval } : {}),
        ...(failureStateParam ? { failure_state: failureStateParam } : {})
      });
      const filteredItems =
        nextState === "healthy"
          ? response.items.filter((item) => item.failure_state === null)
          : response.items;
      tenantWebsiteInventoryOverride = {
        ...response,
        items: filteredItems
      };
    } catch (error) {
      toastError(error, m.crawler_tenant_website_inventory_load_error());
    } finally {
      tenantWebsiteInventoryBusy = false;
    }
  }

  function changeTenantWebsiteInventoryPageSize(value: string) {
    const parsed = Number.parseInt(value, 10);
    if (!Number.isFinite(parsed) || !isCrawlerTenantWebsiteInventoryPageSize(parsed)) {
      return;
    }
    if (parsed === tenantWebsiteInventoryPageSize) return;
    void refreshTenantWebsiteInventory({ pageSize: parsed, resetPage: true });
  }

  function handleTenantWebsiteInventorySearchInput(value: string) {
    tenantWebsiteInventorySearch = value;
    if (tenantWebsiteInventorySearchDebounceTimer !== null) {
      clearTimeout(tenantWebsiteInventorySearchDebounceTimer);
    }
    tenantWebsiteInventorySearchDebounceTimer = setTimeout(() => {
      tenantWebsiteInventorySearchDebounceTimer = null;
      void refreshTenantWebsiteInventory({ search: value, resetPage: true });
    }, 300);
  }

  function clearTenantWebsiteInventorySearch() {
    if (tenantWebsiteInventorySearchDebounceTimer !== null) {
      clearTimeout(tenantWebsiteInventorySearchDebounceTimer);
      tenantWebsiteInventorySearchDebounceTimer = null;
    }
    void refreshTenantWebsiteInventory({ search: "", resetPage: true });
  }

  function tenantWebsiteInventoryActiveFilterCount(): number {
    let count = 0;
    if (tenantWebsiteInventorySearch.trim() !== "") count += 1;
    if (tenantWebsiteInventoryIntervalFilter !== "") count += 1;
    if (tenantWebsiteInventoryStateFilter !== "all") count += 1;
    return count;
  }

  function clearTenantWebsiteInventoryFilters() {
    if (tenantWebsiteInventorySearchDebounceTimer !== null) {
      clearTimeout(tenantWebsiteInventorySearchDebounceTimer);
      tenantWebsiteInventorySearchDebounceTimer = null;
    }
    void refreshTenantWebsiteInventory({
      search: "",
      interval: "",
      state: "all",
      resetPage: true
    });
  }

  function openWebsiteDetail(item: CrawlerTenantWebsiteInventoryItem) {
    detailCandidate = item;
  }

  function closeWebsiteDetail() {
    detailCandidate = null;
  }

  function tenantWebsiteInventoryRowStatusClass(item: CrawlerTenantWebsiteInventoryItem) {
    if (item.failure_state === "AUTO_DISABLED") {
      return "border-destructive/35 bg-destructive/8 text-destructive";
    }
    if (item.failure_state === "BACKED_OFF") {
      return "border-caution/40 bg-caution/8 text-caution";
    }
    return "border-positive-default/40 bg-positive-dimmer text-positive-stronger";
  }

  function formatRelativeOrAbsolute(value: string | null): string {
    if (!value) return "—";
    return formatCrawlerDateTime(value);
  }

  function toggleTenantWebsiteInventoryRowSelection(websiteId: string, next: boolean) {
    if (next) {
      tenantWebsiteInventorySelection.add(websiteId);
    } else {
      tenantWebsiteInventorySelection.delete(websiteId);
    }
  }

  function tenantWebsiteInventoryAllVisibleSelected(): boolean {
    if (!visibleTenantWebsiteInventory || visibleTenantWebsiteInventory.items.length === 0) {
      return false;
    }
    return visibleTenantWebsiteInventory.items.every((item) =>
      tenantWebsiteInventorySelection.has(item.website_id)
    );
  }

  function tenantWebsiteInventorySomeVisibleSelected(): boolean {
    if (!visibleTenantWebsiteInventory) return false;
    return visibleTenantWebsiteInventory.items.some((item) =>
      tenantWebsiteInventorySelection.has(item.website_id)
    );
  }

  function toggleTenantWebsiteInventorySelectAllVisible(next: boolean) {
    if (!visibleTenantWebsiteInventory) return;
    for (const item of visibleTenantWebsiteInventory.items) {
      if (next) {
        tenantWebsiteInventorySelection.add(item.website_id);
      } else {
        tenantWebsiteInventorySelection.delete(item.website_id);
      }
    }
  }

  function clearTenantWebsiteInventorySelection() {
    tenantWebsiteInventorySelection.clear();
  }

  function detailLabelForInlineSave(websiteId: string): string {
    return (
      detailCandidate?.name?.trim() ||
      detailCandidate?.url ||
      m.crawler_active_inventory_unknown_website({ id: websiteId.slice(0, 8) })
    );
  }
</script>

<svelte:head>
  <title>Eneo.ai - {m.crawler_settings()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.crawler_settings()} />
  </Page.Header>
  <Page.Main>
    <div class="crawler-admin-wrap mx-auto w-full max-w-[1280px] pt-6 sm:pt-10">
      <p class="text-secondary -mt-4 mb-6 max-w-[64ch] px-2 text-[15px] leading-relaxed sm:pr-12">
        {m.crawler_settings_subtitle()}
      </p>

      <KpiSummary
        {visibleActiveInventory}
        failureInventory={data.crawlerFailureInventory}
        scheduledAggregate={data.crawlerScheduledAggregate}
        {currentTab}
        onSelectTab={(tab) => (currentTab = tab)}
      />

      <Tabs.Root
        value={currentTab}
        onValueChange={(value) => {
          if (value) currentTab = value as CrawlerAdminTab;
        }}
        class="mb-10"
      >
        <div class="-mx-2 mb-4 overflow-x-auto px-2">
          <Tabs.List class="inline-flex w-max min-w-full gap-1">
            <Tabs.Trigger
              value="operations"
              aria-label={m.crawler_admin_tab_operations()}
              class="shrink-0"
            >
              {m.crawler_admin_tab_operations()}
              {#if visibleActiveInventory && visibleActiveInventory.total > 0}
                <Badge variant="secondary" class="ml-2 tabular-nums">
                  {visibleActiveInventory.total}
                </Badge>
              {/if}
            </Tabs.Trigger>
            <Tabs.Trigger
              value="websites"
              aria-label={m.crawler_admin_tab_websites()}
              class="shrink-0"
            >
              {m.crawler_admin_tab_websites()}
              {#if visibleTenantWebsiteInventory && visibleTenantWebsiteInventory.total > 0}
                <Badge variant="secondary" class="ml-2 tabular-nums">
                  {visibleTenantWebsiteInventory.total}
                </Badge>
              {/if}
            </Tabs.Trigger>
            <Tabs.Trigger value="health" aria-label={m.crawler_admin_tab_health()} class="shrink-0">
              {m.crawler_admin_tab_health()}
              {#if data.crawlerFailureInventory && data.crawlerFailureInventory.total > 0}
                <Badge variant="secondary" class="ml-2 tabular-nums">
                  {data.crawlerFailureInventory.total}
                </Badge>
              {/if}
            </Tabs.Trigger>
            <Tabs.Trigger
              value="activity"
              aria-label={m.crawler_admin_tab_activity()}
              class="shrink-0"
            >
              {m.crawler_admin_tab_activity()}
            </Tabs.Trigger>
            <Tabs.Trigger
              value="settings"
              aria-label={m.crawler_admin_tab_settings()}
              class="shrink-0"
            >
              {m.crawler_admin_tab_settings()}
            </Tabs.Trigger>
          </Tabs.List>
        </div>

        <Tabs.Content value="operations" class="space-y-0">
          <DriftTab
            activeInventory={visibleActiveInventory}
            visibleItems={visibleActiveInventoryItems}
            lifecycleFilter={activeInventoryLifecycleFilter}
            filterBusy={activeInventoryFilterBusy}
            loadFailed={data.crawlerActiveInventoryLoadFailed}
            page={activeInventoryPage}
            pageSize={activeInventoryPageSize}
            bind:search={activeInventorySearch}
            savingIntervalWebsiteId={dialogs.interval.busy}
            abortingJobId={dialogs.abort.busy}
            resolveRowLabel={resolveHälsaRowLabel}
            onOpenWebsiteDetail={openWebsiteDetail}
            onOpenIntervalDialog={dialogs.interval.openForActiveItem}
            onOpenAbortDialog={dialogs.abort.openFor}
            onRefresh={(options) => void refreshActiveInventory(options)}
            onPageSizeChange={changeActiveInventoryPageSize}
          />
        </Tabs.Content>

        <Tabs.Content value="websites" class="space-y-0">
          <WebbplatserTab
            inventory={{
              visible: visibleTenantWebsiteInventory,
              override: tenantWebsiteInventoryOverride,
              busy: tenantWebsiteInventoryBusy,
              loadFailed: data.crawlerTenantWebsiteInventoryLoadFailed,
              page: tenantWebsiteInventoryPage,
              pageSize: tenantWebsiteInventoryPageSize
            }}
            filters={{
              intervalFilter: tenantWebsiteInventoryIntervalFilter,
              stateFilter: tenantWebsiteInventoryStateFilter,
              stateFilterOptions: tenantWebsiteInventoryStateFilterOptions,
              activeFilterCount: tenantWebsiteInventoryActiveFilterCount
            }}
            selection={{
              ids: tenantWebsiteInventorySelection,
              allVisibleSelected: tenantWebsiteInventoryAllVisibleSelected,
              someVisibleSelected: tenantWebsiteInventorySomeVisibleSelected,
              offPageCount: tenantWebsiteInventoryOffPageSelectionCount
            }}
            mutationState={{
              retryingWebsiteId: dialogs.retry.busy,
              savingIntervalWebsiteId: dialogs.interval.busy,
              resettingCircuitWebsiteId: dialogs.circuitReset.busy,
              deletingWebsiteId: dialogs.delete.busy
            }}
            rowDialogs={{
              onOpenWebsiteDetail: openWebsiteDetail,
              onAdaptRetryDialog: dialogs.retry.openForInventoryItem,
              onAdaptIntervalDialog: dialogs.interval.openForInventoryItem,
              onAdaptCircuitResetDialog: dialogs.circuitReset.openForInventoryItem,
              onOpenDeleteDialog: dialogs.delete.openFor
            }}
            rowStatusClass={tenantWebsiteInventoryRowStatusClass}
            formatLastCrawled={formatRelativeOrAbsolute}
            bind:search={tenantWebsiteInventorySearch}
            onSearchInput={handleTenantWebsiteInventorySearchInput}
            onClearSearch={clearTenantWebsiteInventorySearch}
            onClearFilters={clearTenantWebsiteInventoryFilters}
            onRefresh={(options) => void refreshTenantWebsiteInventory(options)}
            onChangePageSize={changeTenantWebsiteInventoryPageSize}
            onToggleRowSelection={toggleTenantWebsiteInventoryRowSelection}
            onToggleSelectAllVisible={toggleTenantWebsiteInventorySelectAllVisible}
            onClearSelection={clearTenantWebsiteInventorySelection}
            onOpenBulkIntervalDialog={bulkInterval.open}
          />
        </Tabs.Content>

        <Tabs.Content value="health" class="space-y-0">
          <HälsaTab
            failureInventory={data.crawlerFailureInventory ?? null}
            failureInventoryLoadFailed={data.crawlerFailureInventoryLoadFailed}
            watchdog={{
              visible: visibleWatchdogInterventions,
              loadFailed: data.crawlerWatchdogInterventionsLoadFailed,
              windowDays: data.crawlerWatchdogInterventionsWindowDays,
              page: watchdogInterventionsPage,
              busy: watchdogInterventionsBusy,
              onChangePage: (next) => void changeWatchdogInterventionsPage(next)
            }}
            recentFailures={{
              visible: visibleRecentFailures,
              loadFailed: data.crawlerRecentFailuresLoadFailed,
              windowDays: data.crawlerRecentFailuresWindowDays,
              page: recentFailuresPage,
              busy: recentFailuresBusy,
              onChangePage: (next) => void changeRecentFailuresPage(next)
            }}
            mutationState={{
              retryingWebsiteId: dialogs.retry.busy,
              savingIntervalWebsiteId: dialogs.interval.busy,
              resettingCircuitWebsiteId: dialogs.circuitReset.busy
            }}
            resolveRowLabel={resolveHälsaRowLabel}
            onOpenWebsiteDetail={openWebsiteDetail}
            onOpenRetryDialog={dialogs.retry.openFor}
            onOpenIntervalDialog={dialogs.interval.openForFailureItem}
            onOpenCircuitResetDialog={dialogs.circuitReset.openFor}
          />
        </Tabs.Content>

        <Tabs.Content value="activity" class="space-y-0">
          <AktivitetTab
            {activity}
            resolveRowLabel={resolveHälsaRowLabel}
            onOpenWebsiteDetail={openWebsiteDetail}
            onOpenIntervalDialog={dialogs.interval.openForInventoryItem}
            onOpenRetryDialog={dialogs.retry.openForInventoryItem}
            onOpenDeleteDialog={dialogs.delete.openFor}
          />
        </Tabs.Content>

        <Tabs.Content value="settings" class="space-y-0">
          <InställningarTab initialCrawlerSettings={data.crawlerSettings} {intric} />
        </Tabs.Content>
      </Tabs.Root>
    </div>
  </Page.Main>
</Page.Root>

<WebsiteDetailDialog
  candidate={detailCandidate}
  visibleInventory={visibleTenantWebsiteInventory}
  {intric}
  abortingJobId={dialogs.abort.busy}
  retryingWebsiteId={dialogs.retry.busy}
  savingIntervalWebsiteId={dialogs.interval.busy}
  resettingCircuitWebsiteId={dialogs.circuitReset.busy}
  deletingWebsiteId={dialogs.delete.busy}
  onClose={closeWebsiteDetail}
  onOpenAbortDialog={dialogs.abort.openFor}
  onOpenRetryDialog={dialogs.retry.openForInventoryItem}
  onSaveInterval={(websiteId, newInterval) =>
    dialogs.interval.inlineSave(websiteId, newInterval, detailLabelForInlineSave(websiteId))}
  onOpenCircuitResetDialog={dialogs.circuitReset.openForInventoryItem}
  onOpenDeleteDialog={dialogs.delete.openFor}
/>

<CrawlerAdminDialogs {dialogs} />

<BulkIntervalDialog
  open={bulkInterval.dialogOpen}
  onOpenChange={(open) => {
    if (!open) bulkInterval.close();
  }}
  selectionSize={tenantWebsiteInventorySelection.size}
  draft={bulkInterval.draft}
  setDraft={(next) => (bulkInterval.draft = next)}
  applying={bulkInterval.applying}
  lastResult={bulkInterval.lastResult}
  onApply={bulkInterval.apply}
  onClose={bulkInterval.close}
/>
