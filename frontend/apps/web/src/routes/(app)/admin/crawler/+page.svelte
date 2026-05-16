<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { invalidate } from "$app/navigation";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as InputGroup from "$lib/components/ui/input-group/index.js";
  import * as Pagination from "$lib/components/ui/pagination/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import * as Sheet from "$lib/components/ui/sheet/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import * as Tabs from "$lib/components/ui/tabs/index.js";
  import * as ToggleGroup from "$lib/components/ui/toggle-group/index.js";
  import { Page, Settings } from "$lib/components/layout";
  import { toast } from "$lib/components/toast";
  import { getIntric } from "$lib/core/Intric.js";
  import { toastError } from "$lib/core/errors";
  import {
    CRAWLER_SETTINGS_BOOLEAN_FIELDS,
    CRAWLER_SETTINGS_NUMBER_FIELDS,
    CRAWLER_SETTINGS_READ_ONLY_OPTIMIZATIONS,
    getCrawlerSettingDisplayBounds,
    getCrawlerSettingDisplayValue,
    toCrawlerSettingsUpdate,
    validateCrawlerNumberField,
    type CrawlerNumberField,
    type CrawlerSettings,
    type CrawlerSettingsEditableKey,
    type CrawlerSettingsUpdate
  } from "$lib/features/admin/crawlerSettings";
  import {
    CRAWLER_ACTIVE_INVENTORY_DEFAULTS,
    CRAWLER_ACTIVE_INVENTORY_LIFECYCLE_FILTER_OPTIONS,
    CRAWLER_ACTIVE_INVENTORY_PAGE_SIZES,
    canAbortCrawlerActiveInventoryItem,
    getCrawlerAbortConflictMessage,
    getCrawlerActiveInventoryLifecycleFilterLabel,
    getCrawlerActiveInventoryResultLabels,
    getCrawlerActiveInventorySourceLabel,
    getCrawlerActiveInventoryStartedByLabel,
    getCrawlerActiveInventoryStatusLabel,
    getCrawlerActiveInventoryWebsiteLabel,
    isCrawlerActiveInventoryItemRunning,
    isCrawlerActiveInventoryPageSize,
    offsetFromCrawlerActiveInventoryPage,
    type CrawlerActiveInventoryItem,
    type CrawlerActiveInventoryLifecycleFilter,
    type CrawlerActiveInventoryPageSize,
    type CrawlerActiveInventoryResponse
  } from "$lib/features/admin/crawlerActiveInventory";
  import {
    getCrawlerFailureInventoryFailureLabel,
    getCrawlerFailureInventoryLastCrawledLabel,
    getCrawlerFailureInventoryNextStepLabel,
    getCrawlerFailureInventoryStateLabel,
    getCrawlerFailureInventoryStateTooltip,
    getCrawlerFailureInventoryTotalLabel,
    getCrawlerFailureInventoryWebsiteLabel,
    type CrawlerTenantFailureInventoryItem,
    type CrawlerTenantFailureInventoryResponse
  } from "$lib/features/admin/crawlerFailureInventory";
  import {
    getCrawlerCircuitBreakerResetCopy,
    type CrawlerCircuitBreakerResetCandidate,
    type CrawlerCircuitBreakerResetCopy
  } from "$lib/features/admin/crawlerCircuitBreakerReset";
  import {
    CRAWLER_UPDATE_INTERVAL_OPTIONS,
    getCrawlerUpdateIntervalLabel,
    isPausingTransition,
    isResumingTransition,
    type CrawlerUpdateInterval
  } from "$lib/features/admin/crawlerUpdateInterval";
  import { formatCrawlerCount } from "$lib/features/admin/crawlerNumberFormat";
  import type { CrawlRunResultLabel } from "$lib/features/knowledge/crawlOutcomePresentation";
  import {
    CRAWLER_RECENT_FAILURES_PAGE_SIZE,
    getCrawlerRecentFailureOutcomeLabel,
    getCrawlerRecentFailureResultLabels,
    getCrawlerRecentFailureWebsiteLabel,
    offsetFromCrawlerRecentFailuresPage,
    type CrawlerRecentFailuresResponse
  } from "$lib/features/admin/crawlerRecentFailures";
  import {
    CRAWLER_WATCHDOG_INTERVENTIONS_PAGE_SIZE,
    getCrawlerWatchdogInterventionOutcomeLabel,
    getCrawlerWatchdogInterventionResultLabels,
    getCrawlerWatchdogInterventionWebsiteLabel,
    offsetFromCrawlerWatchdogInterventionsPage,
    type CrawlerWatchdogInterventionsResponse
  } from "$lib/features/admin/crawlerWatchdogInterventions";
  import {
    formatCrawlerScheduledCount,
    formatCrawlerScheduledIndexedSize,
    getCrawlerScheduledAggregateTotalLabel,
    getCrawlerScheduledIntervalLabel,
    getCrawlerScheduledUnparseableLabel,
    type CrawlerScheduledAggregateResponse
  } from "$lib/features/admin/crawlerScheduledAggregate";
  import {
    getCrawlerWebsiteProcessingCostLabel,
    getCrawlerWebsiteProcessingFailureLabel,
    getCrawlerWebsiteProcessingFetchedLabel,
    getCrawlerWebsiteProcessingRetainedLabel,
    getCrawlerWebsiteProcessingTotalLabel,
    getCrawlerWebsiteProcessingWebsiteLabel,
    isCrawlerWebsiteProcessingLowRetention,
    isCrawlerWebsiteProcessingSourceSkipDrift,
    type CrawlerTenantWebsiteProcessingAggregateResponse
  } from "$lib/features/admin/crawlerWebsiteProcessing";
  import {
    CRAWLER_TENANT_WEBSITE_INVENTORY_DEFAULTS,
    CRAWLER_TENANT_WEBSITE_INVENTORY_PAGE_SIZES,
    getCrawlerTenantWebsiteInventoryDisplayName,
    getCrawlerTenantWebsiteInventoryOwnerLabel,
    getCrawlerTenantWebsiteInventorySpaceLabel,
    getCrawlerTenantWebsiteInventoryStatusLabel,
    isCrawlerTenantWebsiteInventoryPageSize,
    offsetFromCrawlerTenantWebsiteInventoryPage,
    type CrawlerFailureState,
    type CrawlerTenantWebsiteInventoryItem,
    type CrawlerTenantWebsiteInventoryPageSize,
    type CrawlerTenantWebsiteInventoryResponse,
    type CrawlerTenantWebsiteInventorySort
  } from "$lib/features/admin/crawlerTenantWebsiteInventory";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import { CircleX, ShieldCheck, TriangleAlert } from "lucide-svelte";

  type CrawlerSettingsFormValue = boolean | number | string;
  type CrawlerSettingsFormValues = Record<CrawlerSettingsEditableKey, CrawlerSettingsFormValue>;

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

  let crawlerSettings = $state<CrawlerSettings | null>(null);
  let formValues = $state<CrawlerSettingsFormValues>(emptyFormValues());
  let savedValues = $state<CrawlerSettingsFormValues>(emptyFormValues());
  let savingKey = $state<CrawlerSettingsEditableKey | null>(null);
  let abortDialogOpen = $state(false);
  let abortCandidate = $state<CrawlerActiveInventoryItem | null>(null);
  let abortingJobId = $state<string | null>(null);

  let circuitResetDialogOpen = $state(false);
  let circuitResetCandidate = $state<CrawlerCircuitBreakerResetCandidate | null>(null);
  let resettingCircuitWebsiteId = $state<string | null>(null);

  // Retry-now confirmation state. Uses the same shadcn AlertDialog
  // pattern as abort/circuit-reset/interval. `retryCandidate` carries
  // the minimum the dialog renders + the API needs — id for the call,
  // name for the prompt copy.
  type RetryCandidate = {
    website_id: string;
    website_name: string | null;
    website_url: string | null;
  };
  let retryDialogOpen = $state(false);
  let retryCandidate = $state<RetryCandidate | null>(null);
  let retryingWebsiteId = $state<string | null>(null);

  // Typed shape consumed by the interval-edit dialog so the candidate
  // can come from either the failure inventory (current source) OR the
  // active inventory (new in sub-tranche 2b). Active-inventory rows
  // carry no `website_url`, so the dialog falls back to the website
  // name + a job-id-derived label.
  type IntervalEditCandidate = {
    website_id: string;
    website_name: string | null;
    website_url: string | null;
    update_interval: CrawlerUpdateInterval;
  };

  let intervalDialogOpen = $state(false);
  let intervalCandidate = $state<IntervalEditCandidate | null>(null);
  let intervalDraft = $state<CrawlerUpdateInterval>("never");
  let savingIntervalWebsiteId = $state<string | null>(null);

  let activeInventoryLifecycleFilter = $state<CrawlerActiveInventoryLifecycleFilter>("all");
  let activeInventoryFiltered = $state<CrawlerActiveInventoryResponse | null>(null);
  let activeInventoryFilterBusy = $state(false);
  // The visible active inventory: the filtered client result wins when set,
  // otherwise the unfiltered SSR payload from the page load. Keeping both
  // lets the rapid-toggle UX stay responsive without flashing empty rows.
  const visibleActiveInventory = $derived(activeInventoryFiltered ?? data.crawlerActiveInventory);
  // Pagination state lives on the page, not in the URL, so a tab-switch
  // back to Operations doesn't reset position via SvelteKit `goto`. The
  // SSR-loaded page is always page 1; client-side fetches own subsequent
  // pages.
  let activeInventoryPageSize = $state<CrawlerActiveInventoryPageSize>(
    CRAWLER_ACTIVE_INVENTORY_DEFAULTS.limit
  );
  let activeInventoryPage = $state<number>(1);

  // Free-text filter on the visible active inventory page. Client-side
  // only — narrowing to the rows already on this page is the operator's
  // primary need (cross-page search would need a backend query
  // parameter and is deferred). Lowercased once when typed; rows
  // compare against `website_name` only because the wire shape doesn't
  // carry `website_url` on active rows.
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

  // Recent failures + watchdog interventions both render with a fixed
  // limit per page; client-side state owns the offset so an operator
  // can page through history without a full page reload. The SSR payload
  // is always page 1 — `*Override` carries subsequent fetches so we
  // don't lose the SSR rows if a follow-up fetch fails.
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

  // Webbplatser tab state — tenant-wide governance read powered by the
  // /admin/crawler/websites endpoint. Page 1 + default sort matches the
  // SSR payload; subsequent fetches land in `tenantWebsiteOverride` so a
  // failure keeps the SSR rows visible. Filter values mirror the backend
  // Query params 1:1 so the URL → state → SDK pipeline stays
  // round-trippable.
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

  // Clean up the search-debounce timer on unmount so a late-firing fetch
  // doesn't land in a tab the operator already left. Plain `$effect` with
  // an empty deps block runs once on mount; the returned function runs on
  // destroy.
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

  // Detail Sheet state for the Webbplatser drawer. The drawer reads
  // from `detailCandidateView`, which re-resolves against the visible
  // inventory each time it changes — so an operator-triggered refresh
  // (e.g., after a successful retry) propagates `last_crawled_at`
  // updates into the open drawer without re-opening. Falls back to the
  // original click snapshot if the row left the visible page (filter
  // change, pagination). Closing the Sheet clears `detailCandidate` so
  // a stale row can't survive into the next open.
  let detailSheetOpen = $state<boolean>(false);
  let detailCandidate = $state<CrawlerTenantWebsiteInventoryItem | null>(null);
  const detailCandidateView = $derived<CrawlerTenantWebsiteInventoryItem | null>(
    detailCandidate === null
      ? null
      : (visibleTenantWebsiteInventory?.items.find(
          (item) => item.website_id === detailCandidate?.website_id
        ) ?? detailCandidate)
  );
  const detailActiveJob = $derived<CrawlerActiveInventoryItem | null>(
    detailCandidate === null ? null : findActiveJobForWebsite(detailCandidate.website_id)
  );

  // Drop any open candidate when the SSR payload reference itself
  // changes — that happens on a route load (tenant context switch on
  // the same route, or a forced invalidate), not on client-side
  // pagination (which mutates `tenantWebsiteInventoryOverride` instead
  // of `data.crawlerTenantWebsiteInventory`). The backend gating still
  // rejects a cross-tenant mutation, but the drawer must not present
  // another tenant's website even momentarily.
  let lastSeenSsrInventory: typeof data.crawlerTenantWebsiteInventory = null;
  $effect(() => {
    const current = data.crawlerTenantWebsiteInventory;
    if (lastSeenSsrInventory !== null && current !== lastSeenSsrInventory) {
      detailCandidate = null;
      detailSheetOpen = false;
    }
    lastSeenSsrInventory = current;
  });
  // Status filter chips, computed via `$derived` so message function
  // resolution happens at the locale boundary that other markup uses.
  // Each option carries an inline dot color for the visual badge — the
  // same affordance as `ApiKeyStateFilter`.
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

  const fieldTextByKey: Record<string, () => string> = {
    crawler_hash_skip_title: () => m.crawler_hash_skip_title(),
    crawler_hash_skip_description: () => m.crawler_hash_skip_description(),
    crawler_lastmod_skip_title: () => m.crawler_lastmod_skip_title(),
    crawler_lastmod_skip_description: () => m.crawler_lastmod_skip_description(),
    crawler_lastmod_skip_warning: () => m.crawler_lastmod_skip_warning(),
    crawler_obey_robots_title: () => m.crawler_obey_robots_title(),
    crawler_obey_robots_description: () => m.crawler_obey_robots_description(),
    crawler_autothrottle_title: () => m.crawler_autothrottle_title(),
    crawler_autothrottle_description: () => m.crawler_autothrottle_description(),
    crawler_download_max_size_title: () => m.crawler_download_max_size_title(),
    crawler_download_max_size_description: () => m.crawler_download_max_size_description(),
    crawler_download_timeout_title: () => m.crawler_download_timeout_title(),
    crawler_download_timeout_description: () => m.crawler_download_timeout_description(),
    crawler_dns_timeout_title: () => m.crawler_dns_timeout_title(),
    crawler_dns_timeout_description: () => m.crawler_dns_timeout_description(),
    crawler_retry_times_title: () => m.crawler_retry_times_title(),
    crawler_retry_times_description: () => m.crawler_retry_times_description(),
    crawler_closespider_itemcount_title: () => m.crawler_closespider_itemcount_title(),
    crawler_closespider_itemcount_description: () => m.crawler_closespider_itemcount_description(),
    crawler_max_length_title: () => m.crawler_max_length_title(),
    crawler_max_length_description: () => m.crawler_max_length_description(),
    crawler_stale_threshold_title: () => m.crawler_stale_threshold_title(),
    crawler_stale_threshold_description: () => m.crawler_stale_threshold_description(),
    crawler_queued_stale_title: () => m.crawler_queued_stale_title(),
    crawler_queued_stale_description: () => m.crawler_queued_stale_description(),
    crawler_heartbeat_interval_title: () => m.crawler_heartbeat_interval_title(),
    crawler_heartbeat_interval_description: () => m.crawler_heartbeat_interval_description(),
    crawler_job_max_age_title: () => m.crawler_job_max_age_title(),
    crawler_job_max_age_description: () => m.crawler_job_max_age_description(),
    crawler_unit_mib: () => m.crawler_unit_mib(),
    crawler_unit_seconds: () => m.crawler_unit_seconds(),
    crawler_unit_minutes: () => m.crawler_unit_minutes(),
    crawler_unit_attempts: () => m.crawler_unit_attempts(),
    crawler_unit_items: () => m.crawler_unit_items()
  };

  $effect.pre(() => {
    syncCrawlerSettings(data.crawlerSettings);
  });

  function emptyFormValues(): CrawlerSettingsFormValues {
    return {
      crawl_sitemap_lastmod_skip_enabled: false,
      obey_robots: false,
      autothrottle_enabled: false,
      download_max_size: 0,
      download_timeout: 0,
      dns_timeout: 0,
      retry_times: 0,
      closespider_itemcount: 0,
      crawl_max_length: 0,
      crawl_stale_threshold_minutes: 0,
      queued_stale_threshold_minutes: 0,
      crawl_heartbeat_interval_seconds: 0,
      crawl_job_max_age_seconds: 0
    };
  }

  function buildFormValues(crawlerSettings: CrawlerSettings): CrawlerSettingsFormValues {
    const settings = crawlerSettings.settings;

    return {
      crawl_sitemap_lastmod_skip_enabled: settings.crawl_sitemap_lastmod_skip_enabled,
      obey_robots: settings.obey_robots,
      autothrottle_enabled: settings.autothrottle_enabled,
      download_max_size: getCrawlerSettingDisplayValue(
        "download_max_size",
        settings.download_max_size
      ),
      download_timeout: settings.download_timeout,
      dns_timeout: settings.dns_timeout,
      retry_times: settings.retry_times,
      closespider_itemcount: settings.closespider_itemcount,
      crawl_max_length: settings.crawl_max_length,
      crawl_stale_threshold_minutes: settings.crawl_stale_threshold_minutes,
      queued_stale_threshold_minutes: settings.queued_stale_threshold_minutes,
      crawl_heartbeat_interval_seconds: settings.crawl_heartbeat_interval_seconds,
      crawl_job_max_age_seconds: settings.crawl_job_max_age_seconds
    };
  }

  function syncCrawlerSettings(updatedCrawlerSettings: CrawlerSettings) {
    const nextValues = buildFormValues(updatedCrawlerSettings);
    crawlerSettings = updatedCrawlerSettings;
    formValues = nextValues;
    savedValues = { ...nextValues };
  }

  function fieldText(key: string) {
    return fieldTextByKey[key]?.() ?? key;
  }

  function formatDateTime(value: string) {
    return new Date(value).toLocaleString(getLocale(), {
      dateStyle: "medium",
      timeStyle: "short"
    });
  }

  function resultBadgeClass(color: CrawlRunResultLabel["color"]) {
    if (color === "orange") {
      return "border-caution/40 bg-caution/8 text-caution";
    }
    if (color === "green") {
      return "border-positive-default/40 bg-positive-dimmer text-positive-stronger";
    }
    if (color === "moss") {
      return "border-success/40 bg-secondary text-success";
    }
    if (color === "blue") {
      return "border-accent-default/35 text-accent-default";
    }
    return undefined;
  }

  function activeStatusBadgeClass(lifecycleState: CrawlerActiveInventoryItem["lifecycle_state"]) {
    switch (lifecycleState) {
      case "running_with_progress":
        return "border-positive-default/40 bg-positive-dimmer text-positive-stronger";
      case "running_no_progress":
        return "border-caution/40 bg-caution/8 text-caution";
      case "terminal":
        return "border-border text-muted-foreground";
      case "queued":
        return "border-accent-default/35 text-accent-default";
      default: {
        const exhaustive: never = lifecycleState;
        return exhaustive;
      }
    }
  }

  function failureStateBadgeClass(state: CrawlerTenantFailureInventoryItem["state"]) {
    switch (state) {
      case "BACKED_OFF":
        return "border-caution/40 bg-caution/8 text-caution";
      case "AUTO_DISABLED":
        return "border-destructive/35 bg-destructive/8 text-destructive";
      default: {
        const exhaustive: never = state;
        return exhaustive;
      }
    }
  }

  // KPI button styling. Pressed cards get a saturated ring + bg so the
  // operator always sees which view is active; the warning tint is
  // applied to the failing-count card only when there's actually
  // something failing, so a healthy fleet stays calm.
  function kpiButtonClass(pressed: boolean, tone: "neutral" | "warning" = "neutral"): string {
    const base =
      "focus-visible:ring-ring/50 flex flex-col items-start gap-1.5 rounded-lg border p-4 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none";
    const pressedStyle =
      tone === "warning"
        ? "border-caution/50 bg-caution/8 ring-caution/30 ring-1"
        : "border-accent-default/50 bg-accent-default/8 ring-accent-default/30 ring-1";
    const restingStyle = "border-border bg-background hover:bg-muted";
    return `${base} ${pressed ? pressedStyle : restingStyle}`;
  }

  function rangeHint(field: CrawlerNumberField) {
    const bounds = getCrawlerSettingDisplayBounds(field, crawlerSettings?.specs);
    if (bounds.min === undefined || bounds.max === undefined) return null;
    return m.crawler_setting_range({
      min: bounds.min,
      max: bounds.max,
      unit: fieldText(field.unitKey)
    });
  }

  function numericError(field: CrawlerNumberField) {
    const validation = validateCrawlerNumberField(
      field,
      formValues[field.key],
      crawlerSettings?.specs
    );

    if (validation.valid) return null;
    if (validation.reason === "below_min" && validation.min !== undefined) {
      return m.crawler_setting_min_value({
        min: validation.min,
        unit: fieldText(field.unitKey)
      });
    }
    if (validation.reason === "above_max" && validation.max !== undefined) {
      return m.crawler_setting_max_value({
        max: validation.max,
        unit: fieldText(field.unitKey)
      });
    }
    return m.crawler_setting_invalid_integer();
  }

  function fieldIsDirty(key: CrawlerSettingsEditableKey) {
    return String(formValues[key]) !== String(savedValues[key]);
  }

  function resetField(key: CrawlerSettingsEditableKey) {
    formValues[key] = savedValues[key];
  }

  async function saveCrawlerSettings(
    update: CrawlerSettingsUpdate,
    key: CrawlerSettingsEditableKey
  ) {
    savingKey = key;

    try {
      const updatedSettings = await intric.settings.updateCrawler(update);
      syncCrawlerSettings(updatedSettings as CrawlerSettings);
      await invalidate("admin:crawler-settings");
      toast.success(m.crawler_settings_saved());
    } catch (error) {
      resetField(key);
      toastError(error, m.could_not_update_crawler_settings());
    } finally {
      savingKey = null;
    }
  }

  async function handleToggleCrawlerSetting(key: CrawlerSettingsEditableKey, next: boolean) {
    const current = formValues[key];
    formValues[key] = next;

    const update = toCrawlerSettingsUpdate({ [key]: next }, crawlerSettings?.specs);
    if (Object.keys(update).length === 0) {
      formValues[key] = current;
      return;
    }

    await saveCrawlerSettings(update, key);
  }

  async function handleSaveNumberSetting(field: CrawlerNumberField) {
    const error = numericError(field);
    if (error) {
      toast.error(error);
      return;
    }

    const update = toCrawlerSettingsUpdate(
      { [field.key]: formValues[field.key] },
      crawlerSettings?.specs
    );
    if (Object.keys(update).length === 0) return;

    await saveCrawlerSettings(update, field.key);
  }

  function openAbortDialog(item: CrawlerActiveInventoryItem) {
    abortCandidate = item;
    abortDialogOpen = true;
  }

  function openCircuitResetDialog(item: CrawlerCircuitBreakerResetCandidate) {
    circuitResetCandidate = item;
    circuitResetDialogOpen = true;
  }

  function openRetryDialog(item: {
    website_id: string;
    website_name: string | null;
    website_url: string | null;
  }) {
    retryCandidate = {
      website_id: item.website_id,
      website_name: item.website_name,
      website_url: item.website_url
    };
    retryDialogOpen = true;
  }

  function openIntervalDialog(item: CrawlerTenantFailureInventoryItem) {
    intervalCandidate = {
      website_id: item.website_id,
      website_name: item.website_name,
      website_url: item.website_url,
      update_interval: item.update_interval as CrawlerUpdateInterval
    };
    intervalDraft = item.update_interval as CrawlerUpdateInterval;
    intervalDialogOpen = true;
  }

  function openIntervalDialogForActiveItem(item: CrawlerActiveInventoryItem) {
    // Active inventory rows carry the new tenant-qualified
    // `update_interval` from sub-tranche 2a but no `website_url` (the
    // active inventory wire intentionally omits the URL). Pass null
    // through and let the dialog fall back to the website name.
    if (item.update_interval === null || item.website_id === null) return;
    intervalCandidate = {
      website_id: item.website_id,
      website_name: item.website_name,
      website_url: null,
      update_interval: item.update_interval as CrawlerUpdateInterval
    };
    intervalDraft = item.update_interval as CrawlerUpdateInterval;
    intervalDialogOpen = true;
  }

  async function refreshActiveInventory(opts: {
    filter?: CrawlerActiveInventoryLifecycleFilter;
    page?: number;
    pageSize?: CrawlerActiveInventoryPageSize;
  }) {
    const nextFilter = opts.filter ?? activeInventoryLifecycleFilter;
    const nextPageSize = opts.pageSize ?? activeInventoryPageSize;
    const nextPage = opts.page ?? activeInventoryPage;

    // Filter change resets to page 1 — otherwise the operator would land
    // on an empty page deep into a filtered result.
    const resetPage = opts.filter !== undefined && opts.filter !== activeInventoryLifecycleFilter;
    const effectivePage = resetPage ? 1 : nextPage;

    activeInventoryLifecycleFilter = nextFilter;
    activeInventoryPage = effectivePage;
    activeInventoryPageSize = nextPageSize;

    // When the operator is on page 1 with the default page size AND no
    // filter, the SSR payload already has the right shape — skip the
    // client fetch so the page renders without a spinner flash.
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
    // Reset to page 1 — a larger page size at page N may overshoot total,
    // and "show me 100 starting from row 0" is the expected mental model.
    void refreshActiveInventory({ page: 1, pageSize: parsed });
  }

  // Page through the 7-day recent-failures window without a full
  // SvelteKit invalidate(). Page 1 with the default limit matches the
  // SSR payload exactly, so we clear the override and rely on `data.*`.
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

  // Refresh the Webbplatser inventory with current filter + paging state.
  // Page 1 + default sort + no filters matches the SSR payload exactly,
  // so we short-circuit in that case to avoid a re-fetch flash; any other
  // combination triggers a tenant-scoped client fetch. The override is
  // cleared on the SSR path so the SSR payload owns page 1 again.
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
    // A filter change resets to page 1 so the operator doesn't land
    // mid-way through the narrowed result. The caller can override.
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
      // "Healthy" is a client-side narrowing — the backend has no
      // explicit AUTO_DISABLED / BACKED_OFF filter for "neither". Drop
      // any row that classified into a failure state on this page only;
      // keep `response.total` unchanged so pagination still reflects the
      // true tenant-wide row count instead of being capped at the
      // current-page healthy slice (a tenant where healthy rows span
      // pages would otherwise lose its "next page" affordance).
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
    // Debounce 300ms so each keystroke doesn't hit the SDK. The visible
    // override updates on the trailing edge — the input itself stays in
    // sync via `bind:value` for instant typing feedback.
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
    // Wires the Sheet drawer (C4). The drawer reads the current row
    // from `detailCandidate` so it stays in sync with row updates
    // without re-fetching; closing the Sheet clears the candidate so
    // a stale row can't survive into the next open.
    detailCandidate = item;
    detailSheetOpen = true;
  }

  /**
   * Look up the active job (queued or running) for a given website in
   * the currently loaded active inventory. Returns `null` when no job
   * matches — the drawer disables the "Avbryt aktiv jobb" action in
   * that case so the operator can't try to abort something that isn't
   * running.
   */
  function findActiveJobForWebsite(websiteId: string): CrawlerActiveInventoryItem | null {
    const inventory = visibleActiveInventory;
    if (!inventory) return null;
    for (const item of inventory.items) {
      if (item.website_id === websiteId && canAbortCrawlerActiveInventoryItem(item)) {
        return item;
      }
    }
    return null;
  }

  /**
   * Translate a Webbplatser inventory row into the shape
   * `openIntervalDialog` already expects. Reuses the existing
   * interval-edit dialog so this slice ships no new mutation flow.
   */
  function openIntervalDialogForInventoryItem(item: CrawlerTenantWebsiteInventoryItem) {
    intervalCandidate = {
      website_id: item.website_id,
      website_name: item.name,
      website_url: item.url,
      update_interval: item.update_interval as CrawlerUpdateInterval
    };
    intervalDraft = item.update_interval as CrawlerUpdateInterval;
    intervalDialogOpen = true;
  }

  /**
   * Same pattern for retry — the existing dialog takes a minimal shape;
   * the inventory row already has every field it needs.
   */
  function openRetryDialogForInventoryItem(item: CrawlerTenantWebsiteInventoryItem) {
    openRetryDialog({
      website_id: item.website_id,
      website_name: item.name,
      website_url: item.url
    });
  }

  /**
   * The circuit-breaker reset dialog expects a row that carries
   * `state` (the failure state classifier output) and the same
   * scheduling + counter fields as `CrawlerTenantFailureInventoryItem`.
   * Only callable when `failure_state !== null`; the drawer hides the
   * action otherwise.
   */
  function openCircuitResetDialogForInventoryItem(item: CrawlerTenantWebsiteInventoryItem) {
    if (item.failure_state === null) return;
    // `updated_at` on the failure-inventory candidate type tracks the
    // most recent failure-state observation; the Webbplatser inventory
    // row doesn't carry that field directly, so we use
    // `last_crawled_at` (the closest "most recent worker action"
    // timestamp) and fall back to `created_at` if the website has
    // never been crawled. The reset dialog does not currently render
    // `updated_at`, but the type is satisfied honestly.
    openCircuitResetDialog({
      website_id: item.website_id,
      website_url: item.url,
      website_name: item.name,
      state: item.failure_state,
      update_interval: item.update_interval as CrawlerUpdateInterval,
      consecutive_failures: item.consecutive_failures,
      next_retry_at: item.next_retry_at,
      last_crawled_at: item.last_crawled_at,
      updated_at: item.last_crawled_at ?? item.created_at
    });
  }

  /**
   * Open the abort confirmation for the live active-inventory item
   * matching this website. The drawer guards the call with
   * `findActiveJobForWebsite` so no-op clicks can't happen.
   */
  function openAbortDialogForInventoryItem(item: CrawlerTenantWebsiteInventoryItem) {
    const activeItem = findActiveJobForWebsite(item.website_id);
    if (activeItem === null) return;
    openAbortDialog(activeItem);
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
    return formatDateTime(value);
  }

  async function handleSaveUpdateInterval() {
    const candidate = intervalCandidate;
    if (candidate === null) return;
    const currentInterval = candidate.update_interval as CrawlerUpdateInterval;
    const nextInterval = intervalDraft;
    if (currentInterval === nextInterval) {
      intervalDialogOpen = false;
      intervalCandidate = null;
      return;
    }

    savingIntervalWebsiteId = candidate.website_id;
    const websiteLabel =
      candidate.website_name?.trim() ||
      candidate.website_url ||
      m.crawler_active_inventory_unknown_website({
        id: candidate.website_id.slice(0, 8)
      });

    try {
      await intric.crawlerAdmin.setUpdateInterval(candidate.website_id, nextInterval);
      intervalDialogOpen = false;
      intervalCandidate = null;
      toast.success(m.crawler_update_interval_success({ website: websiteLabel }));
      await Promise.all([
        invalidate("admin:crawler-failure-inventory"),
        invalidate("admin:crawler-scheduled"),
        invalidate("admin:crawler-website-processing"),
        invalidate("admin:crawler-active-inventory")
      ]);
    } catch (error) {
      toastError(error, m.crawler_update_interval_failed());
    } finally {
      savingIntervalWebsiteId = null;
    }
  }

  async function handleResetCircuitBreaker() {
    const candidate = circuitResetCandidate;
    if (candidate === null) return;

    resettingCircuitWebsiteId = candidate.website_id;
    const copy = getCrawlerCircuitBreakerResetCopy(candidate);

    try {
      await intric.crawlerAdmin.resetCircuitBreaker(candidate.website_id);
      circuitResetDialogOpen = false;
      circuitResetCandidate = null;
      toast.success(copy.successMessage);
      await invalidate("admin:crawler-failure-inventory");
    } catch (error) {
      toastError(error, copy.failureMessage);
    } finally {
      resettingCircuitWebsiteId = null;
    }
  }

  async function handleRetryCrawl() {
    const candidate = retryCandidate;
    if (candidate === null) return;
    retryingWebsiteId = candidate.website_id;
    const websiteLabel =
      candidate.website_name?.trim() ||
      candidate.website_url ||
      m.crawler_active_inventory_unknown_website({
        id: candidate.website_id.slice(0, 8)
      });
    try {
      await intric.crawlerAdmin.retryCrawl(candidate.website_id);
      retryDialogOpen = false;
      retryCandidate = null;
      toast.success(m.crawler_retry_success({ website: websiteLabel }));
      // Refresh the views that surface the newly-queued run.
      await Promise.all([
        invalidate("admin:crawler-active-inventory"),
        invalidate("admin:crawler-failure-inventory"),
        invalidate("admin:crawler-recent-failures")
      ]);
    } catch (error) {
      toastError(error, m.crawler_retry_failed());
    } finally {
      retryingWebsiteId = null;
    }
  }

  async function handleAbortCrawl() {
    const candidate = abortCandidate;
    if (candidate === null) return;

    abortingJobId = candidate.job_id;
    const wasRunning = isCrawlerActiveInventoryItemRunning(candidate);

    try {
      await intric.crawlerAdmin.abortCrawl(candidate.job_id);
      abortDialogOpen = false;
      abortCandidate = null;
      toast.success(
        wasRunning ? m.crawler_abort_success_running() : m.crawler_abort_success_queued()
      );
      await Promise.all([
        invalidate("admin:crawler-active-inventory"),
        invalidate("admin:crawler-recent-failures")
      ]);
    } catch (error) {
      const conflictMessage = getCrawlerAbortConflictMessage(error);
      if (conflictMessage) {
        abortDialogOpen = false;
        abortCandidate = null;
        toast.error(conflictMessage);
        await invalidate("admin:crawler-active-inventory");
      } else {
        toastError(error, m.crawler_abort_failed());
      }
    } finally {
      abortingJobId = null;
    }
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
    <Settings.Page>
      <p class="text-secondary -mt-4 mb-6 max-w-[64ch] px-2 text-[15px] leading-relaxed sm:pr-12">
        {m.crawler_settings_subtitle()}
      </p>

      <!--
        KPI summary header: at-a-glance counts for the three load buckets
        the admin cares about (running, needing attention, scheduled).
        Each card is a button that switches to the matching tab so the
        admin can drill in without scrolling. Numbers come from the same
        SSR payloads the tabs already render — no extra network cost.
        Static markup only (no message function calls that could trip
        the toaster hydration fix landed earlier in the session).
        Semantic: these are toggles for the inline Tabs.Root below, not
        navigation, so each card uses aria-pressed + selected styling.
        At mobile (<640px) the grid stacks; at sm+ the three sit
        side-by-side without changing typography.
        -->
      <div
        class="mb-8 grid grid-cols-1 gap-3 sm:grid-cols-3"
        role="group"
        aria-label={m.crawler_summary_aria()}
      >
        <button
          type="button"
          class={kpiButtonClass(currentTab === "operations")}
          aria-pressed={currentTab === "operations"}
          onclick={() => (currentTab = "operations")}
        >
          <span class="text-muted-foreground text-xs tracking-wide uppercase">
            {m.crawler_summary_running_label()}
          </span>
          <span class="text-3xl leading-none font-semibold tabular-nums">
            {visibleActiveInventory ? visibleActiveInventory.total : 0}
          </span>
          <span class="text-muted-foreground text-xs">
            {m.crawler_summary_running_hint()}
          </span>
        </button>
        <button
          type="button"
          class={kpiButtonClass(
            currentTab === "health",
            (data.crawlerFailureInventory?.total ?? 0) > 0 ? "warning" : "neutral"
          )}
          aria-pressed={currentTab === "health"}
          onclick={() => (currentTab = "health")}
        >
          <span class="text-muted-foreground text-xs tracking-wide uppercase">
            {m.crawler_summary_failing_label()}
          </span>
          <span
            class="text-3xl leading-none font-semibold tabular-nums {(data.crawlerFailureInventory
              ?.total ?? 0) > 0
              ? 'text-caution'
              : ''}"
          >
            {data.crawlerFailureInventory ? data.crawlerFailureInventory.total : 0}
          </span>
          <span class="text-muted-foreground text-xs">
            {m.crawler_summary_failing_hint()}
          </span>
        </button>
        <button
          type="button"
          class={kpiButtonClass(currentTab === "activity")}
          aria-pressed={currentTab === "activity"}
          onclick={() => (currentTab = "activity")}
        >
          <span class="text-muted-foreground text-xs tracking-wide uppercase">
            {m.crawler_summary_scheduled_label()}
          </span>
          <span class="text-3xl leading-none font-semibold tabular-nums">
            {data.crawlerScheduledAggregate ? data.crawlerScheduledAggregate.total_websites : 0}
          </span>
          <span class="text-muted-foreground text-xs">
            {m.crawler_summary_scheduled_hint()}
          </span>
        </button>
      </div>

      <Tabs.Root
        value={currentTab}
        onValueChange={(value) => {
          if (value) currentTab = value as CrawlerAdminTab;
        }}
        class="mb-10"
      >
        <!--
          Tabs strip stays single-row at all viewports. Horizontal
          overflow scrolls on narrow phones instead of wrapping to two
          rows (which breaks shadcn TabsList's underline rhythm). The
          -mx-2 px-2 lets the scroll cut bleed against the page edge so
          the rightmost tab doesn't get clipped by Settings.Page padding.
          -->
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
          <Card.Root class="mb-14" aria-labelledby="crawler-active-inventory-title">
            <Card.Header>
              <div class="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
                <div class="flex min-w-0 flex-col gap-1">
                  <h2
                    id="crawler-active-inventory-title"
                    class="text-base leading-snug font-semibold"
                  >
                    {m.crawler_active_inventory_title()}
                  </h2>
                  <Card.Description>{m.crawler_active_inventory_description()}</Card.Description>
                </div>
                {#if visibleActiveInventory}
                  <Badge variant="outline" class="shrink-0 tabular-nums">
                    {m.crawler_active_inventory_count({
                      shown: visibleActiveInventory.items.length,
                      total: visibleActiveInventory.total
                    })}
                  </Badge>
                {/if}
              </div>
              <div class="flex flex-wrap items-end gap-3 pt-3">
                <ToggleGroup.Root
                  type="single"
                  variant="outline"
                  size="sm"
                  value={activeInventoryLifecycleFilter}
                  onValueChange={(next) => {
                    if (next) {
                      void refreshActiveInventory({
                        filter: next as CrawlerActiveInventoryLifecycleFilter
                      });
                    }
                  }}
                  aria-label={m.crawler_active_inventory_filter_label()}
                  disabled={activeInventoryFilterBusy}
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
                  bind:value={activeInventorySearch}
                  placeholder={m.crawler_active_inventory_search_placeholder()}
                  aria-label={m.crawler_active_inventory_search_label()}
                />
              </div>
            </Card.Header>
            <Card.Content class="pt-0">
              {#if data.crawlerActiveInventoryLoadFailed}
                <Alert.Root variant="destructive">
                  <TriangleAlert aria-hidden="true" />
                  <Alert.Description>{m.crawler_active_inventory_load_error()}</Alert.Description>
                </Alert.Root>
              {:else if activeInventoryFilterBusy}
                <p class="text-muted-foreground text-sm">
                  {m.crawler_active_inventory_filter_busy()}
                </p>
              {:else if !visibleActiveInventory || visibleActiveInventory.items.length === 0}
                <p class="text-muted-foreground text-sm">
                  {m.crawler_active_inventory_empty()}
                </p>
              {:else if visibleActiveInventoryItems.length === 0}
                <p class="text-muted-foreground text-sm">
                  {m.crawler_active_inventory_search_empty()}
                </p>
              {:else}
                <div class="overflow-x-auto">
                  <Table.Root class="min-w-[64rem]">
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
                      {#each visibleActiveInventoryItems as activeItem (activeItem.job_id)}
                        {@const sourceLabel = getCrawlerActiveInventorySourceLabel(activeItem)}
                        {@const startedByLabel =
                          getCrawlerActiveInventoryStartedByLabel(activeItem)}
                        <Table.Row>
                          <Table.Cell class="max-w-64">
                            <span
                              class="block truncate font-medium"
                              title={getCrawlerActiveInventoryWebsiteLabel(activeItem)}
                            >
                              {getCrawlerActiveInventoryWebsiteLabel(activeItem)}
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
                              class={activeStatusBadgeClass(activeItem.lifecycle_state)}
                            >
                              {getCrawlerActiveInventoryStatusLabel(activeItem)}
                            </Badge>
                          </Table.Cell>
                          <Table.Cell class="whitespace-normal">
                            <div class="flex flex-wrap gap-1.5">
                              {#each getCrawlerActiveInventoryResultLabels(activeItem) as label (label.label)}
                                <Badge
                                  variant="outline"
                                  class={resultBadgeClass(label.color)}
                                  title={label.tooltip}
                                >
                                  {label.label}
                                </Badge>
                              {/each}
                            </div>
                          </Table.Cell>
                          <Table.Cell class="text-muted-foreground text-right text-xs tabular-nums">
                            {formatDateTime(activeItem.job_updated_at)}
                          </Table.Cell>
                          <Table.Cell class="text-right">
                            <div class="flex flex-wrap items-center justify-end gap-2">
                              {#if activeItem.update_interval !== null && activeItem.website_id !== null}
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  disabled={savingIntervalWebsiteId !== null}
                                  aria-label={m.crawler_update_interval_button_aria({
                                    website: getCrawlerActiveInventoryWebsiteLabel(activeItem)
                                  })}
                                  onclick={() => openIntervalDialogForActiveItem(activeItem)}
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
                                  onclick={() => openAbortDialog(activeItem)}
                                >
                                  <CircleX data-icon="inline-start" aria-hidden="true" />
                                  {abortingJobId === activeItem.job_id
                                    ? m.crawler_abort_button_busy()
                                    : m.crawler_abort_button()}
                                </Button>
                              {/if}
                              {#if !canAbortCrawlerActiveInventoryItem(activeItem) && (activeItem.update_interval === null || activeItem.website_id === null)}
                                <span class="text-muted-foreground text-xs" aria-hidden="true"
                                  >—</span
                                >
                              {/if}
                            </div>
                          </Table.Cell>
                        </Table.Row>
                      {/each}
                    </Table.Body>
                  </Table.Root>
                </div>
                {#if visibleActiveInventory.total > activeInventoryPageSize}
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
                        value={String(activeInventoryPageSize)}
                        onValueChange={(value) => {
                          if (value) changeActiveInventoryPageSize(value);
                        }}
                        disabled={activeInventoryFilterBusy}
                      >
                        <Select.Trigger
                          id="crawler-active-page-size"
                          class="w-20"
                          aria-label={m.crawler_active_inventory_page_size_label()}
                        >
                          {activeInventoryPageSize}
                        </Select.Trigger>
                        <Select.Content>
                          {#each CRAWLER_ACTIVE_INVENTORY_PAGE_SIZES as option (option)}
                            <Select.Item value={String(option)}>{option}</Select.Item>
                          {/each}
                        </Select.Content>
                      </Select.Root>
                    </div>
                    <Pagination.Root
                      count={visibleActiveInventory.total}
                      perPage={activeInventoryPageSize}
                      page={activeInventoryPage}
                      onPageChange={(next) => {
                        if (next === activeInventoryPage || activeInventoryFilterBusy || next < 1)
                          return;
                        void refreshActiveInventory({ page: next });
                      }}
                      class="m-0 w-auto justify-end"
                    >
                      {#snippet children({ pages, currentPage })}
                        <Pagination.Content>
                          <Pagination.Item>
                            <Pagination.PrevButton />
                          </Pagination.Item>
                          {#each pages as page (page.key)}
                            {#if page.type === "ellipsis"}
                              <Pagination.Item>
                                <Pagination.Ellipsis />
                              </Pagination.Item>
                            {:else}
                              <Pagination.Item>
                                <Pagination.Link {page} isActive={currentPage === page.value}>
                                  {page.value}
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
        </Tabs.Content>

        <Tabs.Content value="websites" class="space-y-0">
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
                {#if visibleTenantWebsiteInventory}
                  <Badge variant="outline" class="shrink-0 tabular-nums">
                    {m.crawler_tenant_website_inventory_count({
                      shown: visibleTenantWebsiteInventory.items.length,
                      total: visibleTenantWebsiteInventory.total
                    })}
                  </Badge>
                {/if}
              </div>
              <!--
                Filter strip styled after /admin/api-keys: a flex-wrap row
                with a search Input that fills available space and a set
                of pill toggle buttons for interval + status. The pill
                pattern is a deliberate borrow from `ApiKeyStateFilter`
                so admins paging across the two admin tabs see consistent
                affordances. Clear-all chip appears only when ≥1 filter
                is non-default.
                -->
              <div class="bg-subtle border-default mt-4 flex flex-col gap-3 rounded-lg border p-3">
                <div class="flex flex-wrap items-center gap-2">
                  <div class="relative min-w-[240px] flex-1">
                    <Input
                      type="search"
                      bind:value={tenantWebsiteInventorySearch}
                      oninput={(event) =>
                        handleTenantWebsiteInventorySearchInput(event.currentTarget.value)}
                      placeholder={m.crawler_tenant_website_inventory_search_placeholder()}
                      aria-label={m.crawler_tenant_website_inventory_search_label()}
                      class="pr-9"
                    />
                    {#if tenantWebsiteInventorySearch.length > 0}
                      <button
                        type="button"
                        class="text-muted-foreground hover:bg-muted focus-visible:ring-ring/50 absolute top-1/2 right-2 -translate-y-1/2 rounded p-1 transition-colors focus-visible:ring-2 focus-visible:outline-none"
                        aria-label={m.crawler_tenant_website_inventory_search_clear()}
                        onclick={clearTenantWebsiteInventorySearch}
                      >
                        <CircleX class="size-4" aria-hidden="true" />
                      </button>
                    {/if}
                  </div>
                  {#if tenantWebsiteInventoryActiveFilterCount() > 0}
                    <Button variant="ghost" size="sm" onclick={clearTenantWebsiteInventoryFilters}>
                      {m.crawler_tenant_website_inventory_clear_filters()}
                    </Button>
                  {/if}
                </div>

                <div
                  role="group"
                  aria-label={m.crawler_tenant_website_inventory_interval_filter_label()}
                  class="flex flex-wrap gap-1.5"
                >
                  <button
                    type="button"
                    aria-pressed={tenantWebsiteInventoryIntervalFilter === ""}
                    onclick={() => refreshTenantWebsiteInventory({ interval: "", resetPage: true })}
                    class={tenantWebsiteInventoryIntervalFilter === ""
                      ? "border-accent-default bg-accent-default/10 text-accent-default ring-accent-default/20 inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium ring-2 transition-all"
                      : "border-border bg-background text-muted-foreground hover:border-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-all"}
                  >
                    {m.crawler_tenant_website_inventory_interval_filter_all()}
                  </button>
                  {#each CRAWLER_UPDATE_INTERVAL_OPTIONS as interval (interval)}
                    {@const isActive = tenantWebsiteInventoryIntervalFilter === interval}
                    <button
                      type="button"
                      aria-pressed={isActive}
                      onclick={() =>
                        refreshTenantWebsiteInventory({
                          interval,
                          resetPage: true
                        })}
                      class={isActive
                        ? "border-accent-default bg-accent-default/10 text-accent-default ring-accent-default/20 inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium ring-2 transition-all"
                        : "border-border bg-background text-muted-foreground hover:border-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-all"}
                    >
                      {getCrawlerUpdateIntervalLabel(interval)}
                    </button>
                  {/each}
                </div>

                <div
                  role="group"
                  aria-label={m.crawler_tenant_website_inventory_state_filter_label()}
                  class="flex flex-wrap gap-1.5"
                >
                  {#each tenantWebsiteInventoryStateFilterOptions as option (option.value)}
                    {@const isActive = tenantWebsiteInventoryStateFilter === option.value}
                    <button
                      type="button"
                      aria-pressed={isActive}
                      onclick={() =>
                        refreshTenantWebsiteInventory({
                          state: option.value,
                          resetPage: true
                        })}
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
            </Card.Header>
            <Card.Content class="pt-0">
              {#if data.crawlerTenantWebsiteInventoryLoadFailed && !tenantWebsiteInventoryOverride}
                <Alert.Root variant="destructive">
                  <TriangleAlert aria-hidden="true" />
                  <Alert.Description>
                    {m.crawler_tenant_website_inventory_load_error()}
                  </Alert.Description>
                </Alert.Root>
              {:else if tenantWebsiteInventoryBusy && !visibleTenantWebsiteInventory}
                <p class="text-muted-foreground text-sm">
                  {m.crawler_tenant_website_inventory_loading()}
                </p>
              {:else if !visibleTenantWebsiteInventory || visibleTenantWebsiteInventory.items.length === 0}
                <p class="text-muted-foreground text-sm">
                  {tenantWebsiteInventoryActiveFilterCount() > 0
                    ? m.crawler_tenant_website_inventory_search_empty()
                    : m.crawler_tenant_website_inventory_empty()}
                </p>
              {:else}
                <div class="overflow-x-auto">
                  <Table.Root class="min-w-[72rem]">
                    <Table.Caption class="sr-only">
                      {m.crawler_tenant_website_inventory_table_caption()}
                    </Table.Caption>
                    <Table.Header>
                      <Table.Row>
                        <Table.Head>
                          {m.crawler_tenant_website_inventory_column_website()}
                        </Table.Head>
                        <Table.Head>
                          {m.crawler_tenant_website_inventory_column_owner()}
                        </Table.Head>
                        <Table.Head>
                          {m.crawler_tenant_website_inventory_column_space()}
                        </Table.Head>
                        <Table.Head>
                          {m.crawler_tenant_website_inventory_column_schedule()}
                        </Table.Head>
                        <Table.Head class="text-right">
                          {m.crawler_tenant_website_inventory_column_last_crawled()}
                        </Table.Head>
                        <Table.Head>
                          {m.crawler_tenant_website_inventory_column_status()}
                        </Table.Head>
                        <Table.Head class="text-right">
                          {m.crawler_tenant_website_inventory_column_size()}
                        </Table.Head>
                      </Table.Row>
                    </Table.Header>
                    <Table.Body>
                      {#each visibleTenantWebsiteInventory.items as websiteItem (websiteItem.website_id)}
                        {@const displayName =
                          getCrawlerTenantWebsiteInventoryDisplayName(websiteItem)}
                        <Table.Row
                          class="hover:bg-muted/40 focus-within:bg-muted/40 cursor-pointer"
                          onclick={() => openWebsiteDetail(websiteItem)}
                        >
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
                            <span
                              class="block truncate"
                              title={getCrawlerTenantWebsiteInventoryOwnerLabel(websiteItem)}
                            >
                              {getCrawlerTenantWebsiteInventoryOwnerLabel(websiteItem)}
                            </span>
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
                            {formatRelativeOrAbsolute(websiteItem.last_crawled_at)}
                          </Table.Cell>
                          <Table.Cell>
                            <Badge
                              variant="outline"
                              class={tenantWebsiteInventoryRowStatusClass(websiteItem)}
                            >
                              {getCrawlerTenantWebsiteInventoryStatusLabel(websiteItem)}
                            </Badge>
                          </Table.Cell>
                          <Table.Cell class="text-right text-sm tabular-nums">
                            {websiteItem.size > 0
                              ? formatCrawlerScheduledIndexedSize(websiteItem.size)
                              : "—"}
                          </Table.Cell>
                        </Table.Row>
                      {/each}
                    </Table.Body>
                  </Table.Root>
                </div>
                {#if visibleTenantWebsiteInventory.total > tenantWebsiteInventoryPageSize}
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
                        value={String(tenantWebsiteInventoryPageSize)}
                        onValueChange={(value) => {
                          if (value) changeTenantWebsiteInventoryPageSize(value);
                        }}
                        disabled={tenantWebsiteInventoryBusy}
                      >
                        <Select.Trigger
                          id="crawler-websites-page-size"
                          class="w-20"
                          aria-label={m.crawler_active_inventory_page_size_label()}
                        >
                          {tenantWebsiteInventoryPageSize}
                        </Select.Trigger>
                        <Select.Content>
                          {#each CRAWLER_TENANT_WEBSITE_INVENTORY_PAGE_SIZES as option (option)}
                            <Select.Item value={String(option)}>{option}</Select.Item>
                          {/each}
                        </Select.Content>
                      </Select.Root>
                    </div>
                    <Pagination.Root
                      count={visibleTenantWebsiteInventory.total}
                      perPage={tenantWebsiteInventoryPageSize}
                      page={tenantWebsiteInventoryPage}
                      onPageChange={(next) => {
                        if (
                          next === tenantWebsiteInventoryPage ||
                          tenantWebsiteInventoryBusy ||
                          next < 1
                        )
                          return;
                        void refreshTenantWebsiteInventory({ page: next });
                      }}
                      class="m-0 w-auto justify-end"
                    >
                      {#snippet children({ pages, currentPage })}
                        <Pagination.Content>
                          <Pagination.Item>
                            <Pagination.PrevButton />
                          </Pagination.Item>
                          {#each pages as page (page.key)}
                            {#if page.type === "ellipsis"}
                              <Pagination.Item>
                                <Pagination.Ellipsis />
                              </Pagination.Item>
                            {:else}
                              <Pagination.Item>
                                <Pagination.Link {page} isActive={currentPage === page.value}>
                                  {page.value}
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
        </Tabs.Content>

        <Tabs.Content value="health" class="space-y-0">
          <Card.Root class="mb-14" aria-labelledby="crawler-failure-inventory-title">
            <Card.Header>
              <div class="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
                <div class="flex min-w-0 flex-col gap-1">
                  <h2
                    id="crawler-failure-inventory-title"
                    class="text-base leading-snug font-semibold"
                  >
                    {m.crawler_failure_inventory_title()}
                  </h2>
                  <Card.Description>{m.crawler_failure_inventory_description()}</Card.Description>
                </div>
                {#if data.crawlerFailureInventory}
                  <Badge variant="outline" class="shrink-0 tabular-nums">
                    {getCrawlerFailureInventoryTotalLabel(data.crawlerFailureInventory)}
                  </Badge>
                {/if}
              </div>
            </Card.Header>
            <Card.Content class="pt-0">
              {#if data.crawlerFailureInventoryLoadFailed}
                <Alert.Root variant="destructive">
                  <TriangleAlert aria-hidden="true" />
                  <Alert.Description>{m.crawler_failure_inventory_load_error()}</Alert.Description>
                </Alert.Root>
              {:else if !data.crawlerFailureInventory || data.crawlerFailureInventory.items.length === 0}
                <p class="text-muted-foreground text-sm">
                  {m.crawler_failure_inventory_empty()}
                </p>
              {:else}
                <div class="overflow-x-auto">
                  <Table.Root class="min-w-[58rem]">
                    <Table.Caption class="sr-only">
                      {m.crawler_failure_inventory_table_caption()}
                    </Table.Caption>
                    <Table.Header>
                      <Table.Row>
                        <Table.Head>{m.crawler_failure_inventory_column_website()}</Table.Head>
                        <Table.Head>{m.crawler_failure_inventory_column_state()}</Table.Head>
                        <Table.Head>{m.crawler_failure_inventory_column_failures()}</Table.Head>
                        <Table.Head>{m.crawler_failure_inventory_column_next_step()}</Table.Head>
                        <Table.Head class="text-right">
                          {m.crawler_failure_inventory_column_last_crawled()}
                        </Table.Head>
                        <Table.Head class="text-right">
                          {m.crawler_failure_inventory_column_action()}
                        </Table.Head>
                      </Table.Row>
                    </Table.Header>
                    <Table.Body>
                      {#each data.crawlerFailureInventory.items as failureState (failureState.website_id)}
                        {@const resetCopy = getCrawlerCircuitBreakerResetCopy(failureState)}
                        {@const isResettingThis =
                          resettingCircuitWebsiteId === failureState.website_id}
                        <Table.Row>
                          <Table.Cell class="max-w-64">
                            <span
                              class="block truncate font-medium"
                              title={getCrawlerFailureInventoryWebsiteLabel(failureState)}
                            >
                              {getCrawlerFailureInventoryWebsiteLabel(failureState)}
                            </span>
                          </Table.Cell>
                          <Table.Cell>
                            <Badge
                              variant="outline"
                              class={failureStateBadgeClass(failureState.state)}
                              title={getCrawlerFailureInventoryStateTooltip(failureState)}
                            >
                              {getCrawlerFailureInventoryStateLabel(failureState)}
                            </Badge>
                          </Table.Cell>
                          <Table.Cell class="tabular-nums">
                            {getCrawlerFailureInventoryFailureLabel(failureState)}
                          </Table.Cell>
                          <Table.Cell
                            class="text-muted-foreground max-w-80 text-sm whitespace-normal"
                          >
                            {getCrawlerFailureInventoryNextStepLabel(failureState)}
                          </Table.Cell>
                          <Table.Cell class="text-muted-foreground text-right text-xs tabular-nums">
                            {getCrawlerFailureInventoryLastCrawledLabel(failureState)}
                          </Table.Cell>
                          <Table.Cell class="text-right">
                            <div class="flex flex-wrap items-center justify-end gap-2">
                              <Button
                                variant="ghost"
                                size="sm"
                                aria-label={m.crawler_retry_button_aria({
                                  website: getCrawlerFailureInventoryWebsiteLabel(failureState)
                                })}
                                disabled={retryingWebsiteId !== null}
                                onclick={() => openRetryDialog(failureState)}
                              >
                                {retryingWebsiteId === failureState.website_id
                                  ? m.crawler_retry_button_busy()
                                  : m.crawler_retry_button()}
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                aria-label={m.crawler_update_interval_button_aria({
                                  website: getCrawlerFailureInventoryWebsiteLabel(failureState)
                                })}
                                disabled={savingIntervalWebsiteId !== null}
                                onclick={() => openIntervalDialog(failureState)}
                              >
                                {savingIntervalWebsiteId === failureState.website_id
                                  ? m.crawler_update_interval_dialog_busy()
                                  : m.crawler_update_interval_button()}
                              </Button>
                              <Button
                                variant="outline"
                                size="sm"
                                aria-label={resetCopy.ariaLabel}
                                disabled={resettingCircuitWebsiteId !== null}
                                onclick={() => openCircuitResetDialog(failureState)}
                              >
                                {isResettingThis
                                  ? resetCopy.busyLabel
                                  : failureState.state === "AUTO_DISABLED"
                                    ? m.crawler_circuit_breaker_reset_button_paused()
                                    : m.crawler_circuit_breaker_reset_button_backed_off()}
                              </Button>
                            </div>
                          </Table.Cell>
                        </Table.Row>
                      {/each}
                    </Table.Body>
                  </Table.Root>
                </div>
              {/if}
            </Card.Content>
          </Card.Root>
          <Card.Root class="mb-14" aria-labelledby="crawler-watchdog-interventions-title">
            <Card.Header>
              <div class="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
                <div class="flex min-w-0 flex-col gap-1">
                  <h2
                    id="crawler-watchdog-interventions-title"
                    class="text-base leading-snug font-semibold"
                  >
                    {m.crawler_watchdog_interventions_title()}
                  </h2>
                  <Card.Description>
                    {m.crawler_watchdog_interventions_description({
                      days: data.crawlerWatchdogInterventionsWindowDays
                    })}
                  </Card.Description>
                </div>
                {#if visibleWatchdogInterventions}
                  <Badge variant="outline" class="shrink-0 tabular-nums">
                    {m.crawler_watchdog_interventions_count({
                      shown: visibleWatchdogInterventions.items.length,
                      total: visibleWatchdogInterventions.total
                    })}
                  </Badge>
                {/if}
              </div>
            </Card.Header>
            <Card.Content class="pt-0">
              {#if data.crawlerWatchdogInterventionsLoadFailed}
                <Alert.Root variant="destructive">
                  <TriangleAlert aria-hidden="true" />
                  <Alert.Description
                    >{m.crawler_watchdog_interventions_load_error()}</Alert.Description
                  >
                </Alert.Root>
              {:else if !visibleWatchdogInterventions || visibleWatchdogInterventions.items.length === 0}
                <p class="text-muted-foreground text-sm">
                  {m.crawler_watchdog_interventions_empty({
                    days: data.crawlerWatchdogInterventionsWindowDays
                  })}
                </p>
              {:else}
                <div class="overflow-x-auto">
                  <Table.Root class="min-w-[56rem]">
                    <Table.Caption class="sr-only">
                      {m.crawler_watchdog_interventions_table_caption()}
                    </Table.Caption>
                    <Table.Header>
                      <Table.Row>
                        <Table.Head>{m.crawler_watchdog_interventions_column_website()}</Table.Head>
                        <Table.Head>{m.crawler_watchdog_interventions_column_outcome()}</Table.Head>
                        <Table.Head>{m.crawler_watchdog_interventions_column_activity()}</Table.Head
                        >
                        <Table.Head class="text-right">
                          {m.crawler_watchdog_interventions_column_finished()}
                        </Table.Head>
                      </Table.Row>
                    </Table.Header>
                    <Table.Body>
                      {#each visibleWatchdogInterventions.items as intervention (intervention.crawl_run_id)}
                        <Table.Row>
                          <Table.Cell class="max-w-64">
                            <span
                              class="block truncate font-medium"
                              title={getCrawlerWatchdogInterventionWebsiteLabel(intervention)}
                            >
                              {getCrawlerWatchdogInterventionWebsiteLabel(intervention)}
                            </span>
                          </Table.Cell>
                          <Table.Cell class="max-w-72 whitespace-normal">
                            <span class="text-sm">
                              {getCrawlerWatchdogInterventionOutcomeLabel(intervention)}
                            </span>
                          </Table.Cell>
                          <Table.Cell class="whitespace-normal">
                            <div class="flex flex-wrap gap-1.5">
                              {#each getCrawlerWatchdogInterventionResultLabels(intervention) as label (label.label)}
                                <Badge
                                  variant="outline"
                                  class={resultBadgeClass(label.color)}
                                  title={label.tooltip}
                                >
                                  {label.label}
                                </Badge>
                              {/each}
                            </div>
                          </Table.Cell>
                          <Table.Cell class="text-muted-foreground text-right text-xs tabular-nums">
                            {formatDateTime(intervention.finished_at)}
                          </Table.Cell>
                        </Table.Row>
                      {/each}
                    </Table.Body>
                  </Table.Root>
                </div>
                {#if visibleWatchdogInterventions.total > CRAWLER_WATCHDOG_INTERVENTIONS_PAGE_SIZE}
                  <div class="mt-4 flex items-center justify-end">
                    <Pagination.Root
                      count={visibleWatchdogInterventions.total}
                      perPage={CRAWLER_WATCHDOG_INTERVENTIONS_PAGE_SIZE}
                      page={watchdogInterventionsPage}
                      onPageChange={(next) => {
                        void changeWatchdogInterventionsPage(next);
                      }}
                      class="m-0 w-auto justify-end"
                    >
                      {#snippet children({ pages, currentPage })}
                        <Pagination.Content>
                          <Pagination.Item>
                            <Pagination.PrevButton />
                          </Pagination.Item>
                          {#each pages as page (page.key)}
                            {#if page.type === "ellipsis"}
                              <Pagination.Item>
                                <Pagination.Ellipsis />
                              </Pagination.Item>
                            {:else}
                              <Pagination.Item>
                                <Pagination.Link {page} isActive={currentPage === page.value}>
                                  {page.value}
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

          <Card.Root class="mb-14" aria-labelledby="crawler-recent-failures-title">
            <Card.Header>
              <div class="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
                <div class="flex min-w-0 flex-col gap-1">
                  <h2
                    id="crawler-recent-failures-title"
                    class="text-base leading-snug font-semibold"
                  >
                    {m.crawler_recent_failures_title()}
                  </h2>
                  <Card.Description>
                    {m.crawler_recent_failures_description({
                      days: data.crawlerRecentFailuresWindowDays
                    })}
                  </Card.Description>
                </div>
                {#if visibleRecentFailures}
                  <Badge variant="outline" class="shrink-0 tabular-nums">
                    {m.crawler_recent_failures_count({
                      shown: visibleRecentFailures.items.length,
                      total: visibleRecentFailures.total
                    })}
                  </Badge>
                {/if}
              </div>
            </Card.Header>
            <Card.Content class="pt-0">
              {#if data.crawlerRecentFailuresLoadFailed}
                <Alert.Root variant="destructive">
                  <TriangleAlert aria-hidden="true" />
                  <Alert.Description>{m.crawler_recent_failures_load_error()}</Alert.Description>
                </Alert.Root>
              {:else if !visibleRecentFailures || visibleRecentFailures.items.length === 0}
                <p class="text-muted-foreground text-sm">
                  {m.crawler_recent_failures_empty({
                    days: data.crawlerRecentFailuresWindowDays
                  })}
                </p>
              {:else}
                <div class="overflow-x-auto">
                  <Table.Root class="min-w-[56rem]">
                    <Table.Caption class="sr-only">
                      {m.crawler_recent_failures_table_caption()}
                    </Table.Caption>
                    <Table.Header>
                      <Table.Row>
                        <Table.Head>{m.crawler_recent_failures_column_website()}</Table.Head>
                        <Table.Head>{m.crawler_recent_failures_column_outcome()}</Table.Head>
                        <Table.Head>{m.crawler_recent_failures_column_activity()}</Table.Head>
                        <Table.Head class="text-right">
                          {m.crawler_recent_failures_column_finished()}
                        </Table.Head>
                      </Table.Row>
                    </Table.Header>
                    <Table.Body>
                      {#each visibleRecentFailures.items as failure (failure.crawl_run_id)}
                        <Table.Row>
                          <Table.Cell class="max-w-64">
                            <span
                              class="block truncate font-medium"
                              title={getCrawlerRecentFailureWebsiteLabel(failure)}
                            >
                              {getCrawlerRecentFailureWebsiteLabel(failure)}
                            </span>
                          </Table.Cell>
                          <Table.Cell class="max-w-72 whitespace-normal">
                            <span class="text-sm"
                              >{getCrawlerRecentFailureOutcomeLabel(failure)}</span
                            >
                          </Table.Cell>
                          <Table.Cell class="whitespace-normal">
                            <div class="flex flex-wrap gap-1.5">
                              {#each getCrawlerRecentFailureResultLabels(failure) as label (label.label)}
                                <Badge
                                  variant="outline"
                                  class={resultBadgeClass(label.color)}
                                  title={label.tooltip}
                                >
                                  {label.label}
                                </Badge>
                              {/each}
                            </div>
                          </Table.Cell>
                          <Table.Cell class="text-muted-foreground text-right text-xs tabular-nums">
                            {formatDateTime(failure.finished_at)}
                          </Table.Cell>
                        </Table.Row>
                      {/each}
                    </Table.Body>
                  </Table.Root>
                </div>
                {#if visibleRecentFailures.total > CRAWLER_RECENT_FAILURES_PAGE_SIZE}
                  <div class="mt-4 flex items-center justify-end">
                    <Pagination.Root
                      count={visibleRecentFailures.total}
                      perPage={CRAWLER_RECENT_FAILURES_PAGE_SIZE}
                      page={recentFailuresPage}
                      onPageChange={(next) => {
                        void changeRecentFailuresPage(next);
                      }}
                      class="m-0 w-auto justify-end"
                    >
                      {#snippet children({ pages, currentPage })}
                        <Pagination.Content>
                          <Pagination.Item>
                            <Pagination.PrevButton />
                          </Pagination.Item>
                          {#each pages as page (page.key)}
                            {#if page.type === "ellipsis"}
                              <Pagination.Item>
                                <Pagination.Ellipsis />
                              </Pagination.Item>
                            {:else}
                              <Pagination.Item>
                                <Pagination.Link {page} isActive={currentPage === page.value}>
                                  {page.value}
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
        </Tabs.Content>

        <Tabs.Content value="activity" class="space-y-0">
          <Card.Root class="mb-14" aria-labelledby="crawler-scheduled-title">
            <Card.Header>
              <div class="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
                <div class="flex min-w-0 flex-col gap-1">
                  <h2 id="crawler-scheduled-title" class="text-base leading-snug font-semibold">
                    {m.crawler_scheduled_title()}
                  </h2>
                  <Card.Description>{m.crawler_scheduled_description()}</Card.Description>
                </div>
                {#if data.crawlerScheduledAggregate}
                  <Badge variant="outline" class="shrink-0 tabular-nums">
                    {getCrawlerScheduledAggregateTotalLabel(data.crawlerScheduledAggregate)}
                  </Badge>
                {/if}
              </div>
            </Card.Header>
            <Card.Content class="pt-0">
              {#if data.crawlerScheduledAggregateLoadFailed}
                <Alert.Root variant="destructive">
                  <TriangleAlert aria-hidden="true" />
                  <Alert.Description>{m.crawler_scheduled_load_error()}</Alert.Description>
                </Alert.Root>
              {:else if !data.crawlerScheduledAggregate || data.crawlerScheduledAggregate.total_websites === 0}
                <p class="text-muted-foreground text-sm">
                  {m.crawler_scheduled_empty()}
                </p>
              {:else}
                {@const unparseableLabel = getCrawlerScheduledUnparseableLabel(
                  data.crawlerScheduledAggregate
                )}
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
                        {#each data.crawlerScheduledAggregate.buckets as bucket (bucket.update_interval)}
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
                  <h2
                    id="crawler-website-processing-title"
                    class="text-base leading-snug font-semibold"
                  >
                    {m.crawler_website_processing_title()}
                  </h2>
                  <Card.Description>
                    {m.crawler_website_processing_description({
                      days: data.crawlerWebsiteProcessingWindowDays
                    })}
                  </Card.Description>
                </div>
                {#if data.crawlerWebsiteProcessing}
                  <Badge variant="outline" class="shrink-0 tabular-nums">
                    {getCrawlerWebsiteProcessingTotalLabel(data.crawlerWebsiteProcessing)}
                  </Badge>
                {/if}
              </div>
            </Card.Header>
            <Card.Content class="pt-0">
              {#if data.crawlerWebsiteProcessingLoadFailed}
                <Alert.Root variant="destructive">
                  <TriangleAlert aria-hidden="true" />
                  <Alert.Description>{m.crawler_website_processing_load_error()}</Alert.Description>
                </Alert.Root>
              {:else if !data.crawlerWebsiteProcessing || data.crawlerWebsiteProcessing.items.length === 0}
                <p class="text-muted-foreground text-sm">
                  {m.crawler_website_processing_empty({
                    days: data.crawlerWebsiteProcessingWindowDays
                  })}
                </p>
              {:else}
                <div class="overflow-x-auto">
                  <Table.Root class="min-w-[58rem]">
                    <Table.Caption class="sr-only">
                      {m.crawler_website_processing_table_caption()}
                    </Table.Caption>
                    <Table.Header>
                      <Table.Row>
                        <Table.Head>{m.crawler_website_processing_column_website()}</Table.Head>
                        <Table.Head>{m.crawler_website_processing_column_cost()}</Table.Head>
                        <Table.Head>{m.crawler_website_processing_column_runs()}</Table.Head>
                        <Table.Head>{m.crawler_website_processing_column_fetched()}</Table.Head>
                        <Table.Head>{m.crawler_website_processing_column_retained()}</Table.Head>
                        <Table.Head>{m.crawler_website_processing_column_failures()}</Table.Head>
                      </Table.Row>
                    </Table.Header>
                    <Table.Body>
                      {#each data.crawlerWebsiteProcessing.items as processingItem (processingItem.website_id)}
                        {@const failureLabel =
                          getCrawlerWebsiteProcessingFailureLabel(processingItem)}
                        <Table.Row>
                          <Table.Cell class="max-w-64">
                            <span
                              class="block truncate font-medium"
                              title={getCrawlerWebsiteProcessingWebsiteLabel(processingItem)}
                            >
                              {getCrawlerWebsiteProcessingWebsiteLabel(processingItem)}
                            </span>
                          </Table.Cell>
                          <Table.Cell>
                            <Badge
                              variant="outline"
                              class="tabular-nums"
                              title={m.crawler_website_processing_cost_hint()}
                            >
                              {getCrawlerWebsiteProcessingCostLabel(processingItem)}
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
                              {#if isCrawlerWebsiteProcessingLowRetention(processingItem)}
                                <Badge
                                  variant="outline"
                                  class="border-caution/40 bg-caution/8 text-caution"
                                  title={m.crawler_website_processing_low_retention_tooltip()}
                                >
                                  {m.crawler_website_processing_low_retention_badge()}
                                </Badge>
                              {/if}
                              {#if isCrawlerWebsiteProcessingSourceSkipDrift(processingItem)}
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
              {/if}
            </Card.Content>
          </Card.Root>
        </Tabs.Content>

        <Tabs.Content value="settings" class="space-y-0">
          <Card.Root class="mb-14" aria-labelledby="crawler-builtin-card-title">
            <Card.Header>
              <div class="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
                <div class="flex min-w-0 flex-col gap-1">
                  <h2 id="crawler-builtin-card-title" class="text-base leading-snug font-semibold">
                    {m.crawler_builtin_card_title()}
                  </h2>
                  <Card.Description>{m.crawler_builtin_card_description()}</Card.Description>
                </div>
                <Badge variant="default" class="shrink-0">
                  {m.crawler_built_in_badge()}
                </Badge>
              </div>
            </Card.Header>
            <Card.Content class="flex flex-col gap-2 pt-0">
              {#each CRAWLER_SETTINGS_READ_ONLY_OPTIMIZATIONS as optimization (optimization.key)}
                <div class="flex items-start gap-3">
                  <ShieldCheck
                    class="text-accent-default mt-0.5 size-5 shrink-0"
                    aria-hidden="true"
                  />
                  <div class="flex min-w-0 flex-col gap-1">
                    <h3 class="text-sm font-medium">{fieldText(optimization.titleKey)}</h3>
                    <p class="text-muted-foreground text-sm leading-relaxed">
                      {fieldText(optimization.descriptionKey)}
                    </p>
                  </div>
                </div>
              {/each}
            </Card.Content>
          </Card.Root>

          <Settings.Group title={m.crawler_controls()}>
            <p class="text-secondary -mt-2 max-w-[64ch] pr-12 pl-2 text-sm leading-relaxed">
              {m.crawler_controls_subtitle()}
            </p>

            {#each CRAWLER_SETTINGS_BOOLEAN_FIELDS as field (field.key)}
              <Settings.Row
                title={fieldText(field.titleKey)}
                description={fieldText(field.descriptionKey)}
              >
                <div slot="description">
                  {#if field.warningKey}
                    <Alert.Root class="border-caution/35 bg-caution/8 dark:bg-caution/12 mt-2">
                      <TriangleAlert class="text-caution" aria-hidden="true" />
                      <Alert.Description class="text-caution">
                        {fieldText(field.warningKey)}
                      </Alert.Description>
                    </Alert.Root>
                  {/if}
                </div>
                <div class="flex items-center justify-end pt-1">
                  <Switch
                    checked={Boolean(formValues[field.key])}
                    onCheckedChange={(next) => void handleToggleCrawlerSetting(field.key, next)}
                    disabled={savingKey === field.key}
                    aria-label={fieldText(field.titleKey)}
                  />
                </div>
              </Settings.Row>
            {/each}
          </Settings.Group>

          <Settings.Group title={m.crawler_limits()}>
            <p class="text-secondary -mt-2 max-w-[64ch] pr-12 pl-2 text-sm leading-relaxed">
              {m.crawler_limits_subtitle()}
            </p>

            {#each CRAWLER_SETTINGS_NUMBER_FIELDS as field (field.key)}
              {@const error = numericError(field)}
              {@const bounds = getCrawlerSettingDisplayBounds(field, crawlerSettings?.specs)}
              {@const range = rangeHint(field)}
              {@const isDirty = fieldIsDirty(field.key)}
              {@const isSaving = savingKey === field.key}
              <Settings.Row
                title={fieldText(field.titleKey)}
                description={fieldText(field.descriptionKey)}
              >
                <Field.Field data-invalid={error ? "true" : undefined}>
                  <Field.Label for={`crawler-setting-${field.key}`} class="sr-only">
                    {fieldText(field.titleKey)}
                  </Field.Label>
                  <div class="flex flex-wrap items-start justify-end gap-2">
                    <div class="flex flex-col items-end gap-1">
                      <InputGroup.Root class="w-44">
                        <InputGroup.Input
                          id={`crawler-setting-${field.key}`}
                          type="number"
                          value={formValues[field.key]}
                          min={bounds.min}
                          max={bounds.max}
                          step={field.step}
                          aria-invalid={Boolean(error)}
                          disabled={isSaving}
                          oninput={(event) => {
                            formValues[field.key] = event.currentTarget.value;
                          }}
                        />
                        <InputGroup.Addon align="inline-end">
                          {fieldText(field.unitKey)}
                        </InputGroup.Addon>
                      </InputGroup.Root>
                      {#if range && !error}
                        <span class="text-muted-foreground text-xs tabular-nums">
                          {range}
                        </span>
                      {/if}
                    </div>
                    <div class="flex items-center gap-1.5">
                      {#if isDirty && !isSaving}
                        <Button variant="ghost" size="sm" onclick={() => resetField(field.key)}>
                          {m.reset()}
                        </Button>
                      {/if}
                      <Button
                        size="sm"
                        disabled={!isDirty || Boolean(error) || isSaving}
                        onclick={() => void handleSaveNumberSetting(field)}
                      >
                        {isSaving ? m.crawler_saving() : m.save()}
                      </Button>
                    </div>
                  </div>
                  {#if error}
                    <Field.Error class="text-right">{error}</Field.Error>
                  {/if}
                </Field.Field>
              </Settings.Row>
            {/each}
          </Settings.Group>
        </Tabs.Content>
      </Tabs.Root>
    </Settings.Page>
  </Page.Main>
</Page.Root>

<!--
  Webbplatser detail drawer. Slides in from the right at ~480px. Reads
  the candidate row from `detailCandidateView` so any update to the
  visible inventory propagates without re-opening. Closing clears
  `detailCandidate` so the next click starts fresh. All actions in the
  footer reuse the existing AlertDialog confirmation flows
  (abort / retry / interval-edit / circuit-reset) — no new mutation
  endpoints in this slice.
  -->
<Sheet.Root
  bind:open={detailSheetOpen}
  onOpenChange={(open) => {
    if (!open) {
      detailCandidate = null;
    }
  }}
>
  <Sheet.Content side="right" class="w-full overflow-y-auto sm:max-w-md">
    {#if detailCandidateView}
      {@const display = getCrawlerTenantWebsiteInventoryDisplayName(detailCandidateView)}
      <Sheet.Header>
        <Sheet.Title class="break-words">
          {display}
        </Sheet.Title>
        {#if detailCandidateView.url && detailCandidateView.url !== display}
          <Sheet.Description class="break-words">
            <!-- External URL displayed as plain text + an "Open" button.
              Rendering as <a href> trips
              svelte/no-navigation-without-resolve; this is an external
              navigation that resolve() doesn't apply to, so we open
              programmatically. The text stays selectable for copy. -->
            <span class="text-foreground">{detailCandidateView.url}</span>
            <button
              type="button"
              class="text-accent-default ml-1 text-xs hover:underline"
              onclick={() => {
                if (detailCandidateView?.url) {
                  window.open(detailCandidateView.url, "_blank", "noopener,noreferrer");
                }
              }}
            >
              {m.crawler_website_detail_open_external()}
            </button>
          </Sheet.Description>
        {/if}
      </Sheet.Header>

      <div class="flex flex-col gap-5 px-4 pb-4">
        <!-- Status pill row, prominent so the operator sees state up top. -->
        <div class="flex items-center gap-2">
          <Badge
            variant="outline"
            class={tenantWebsiteInventoryRowStatusClass(detailCandidateView)}
          >
            {getCrawlerTenantWebsiteInventoryStatusLabel(detailCandidateView)}
          </Badge>
          {#if detailActiveJob !== null}
            <Badge
              variant="outline"
              class="border-accent-default/35 text-accent-default tabular-nums"
            >
              {m.crawler_website_detail_active_job()}
            </Badge>
          {/if}
        </div>

        <!-- Ownership card — space, collection, owner email, created date. -->
        <section aria-labelledby="crawler-website-detail-ownership" class="flex flex-col gap-2">
          <h3
            id="crawler-website-detail-ownership"
            class="text-muted-foreground text-xs tracking-wide uppercase"
          >
            {m.crawler_website_detail_section_ownership()}
          </h3>
          <dl class="grid grid-cols-[max-content_1fr] items-baseline gap-x-3 gap-y-1.5">
            <dt class="text-muted-foreground text-sm">
              {m.crawler_website_detail_field_space()}
            </dt>
            <dd class="text-sm">
              {getCrawlerTenantWebsiteInventorySpaceLabel(detailCandidateView)}
            </dd>
            <dt class="text-muted-foreground text-sm">
              {m.crawler_website_detail_field_owner()}
            </dt>
            <dd class="text-sm">
              {getCrawlerTenantWebsiteInventoryOwnerLabel(detailCandidateView)}
            </dd>
            <dt class="text-muted-foreground text-sm">
              {m.crawler_website_detail_field_created()}
            </dt>
            <dd class="text-sm tabular-nums">
              {formatDateTime(detailCandidateView.created_at)}
            </dd>
          </dl>
        </section>

        <!-- Schedule card. -->
        <section aria-labelledby="crawler-website-detail-schedule" class="flex flex-col gap-2">
          <h3
            id="crawler-website-detail-schedule"
            class="text-muted-foreground text-xs tracking-wide uppercase"
          >
            {m.crawler_website_detail_section_schedule()}
          </h3>
          <dl class="grid grid-cols-[max-content_1fr] items-baseline gap-x-3 gap-y-1.5">
            <dt class="text-muted-foreground text-sm">
              {m.crawler_website_detail_field_interval()}
            </dt>
            <dd class="text-sm">
              {getCrawlerUpdateIntervalLabel(detailCandidateView.update_interval)}
            </dd>
            <dt class="text-muted-foreground text-sm">
              {m.crawler_website_detail_field_last_crawled()}
            </dt>
            <dd class="text-sm tabular-nums">
              {formatRelativeOrAbsolute(detailCandidateView.last_crawled_at)}
            </dd>
            {#if detailCandidateView.failure_state !== null && detailCandidateView.consecutive_failures > 0}
              <dt class="text-muted-foreground text-sm">
                {m.crawler_website_detail_field_consecutive_failures()}
              </dt>
              <dd class="text-sm tabular-nums">
                {detailCandidateView.consecutive_failures}
              </dd>
            {/if}
            {#if detailCandidateView.next_retry_at}
              <dt class="text-muted-foreground text-sm">
                {m.crawler_website_detail_field_next_retry()}
              </dt>
              <dd class="text-sm tabular-nums">
                {formatDateTime(detailCandidateView.next_retry_at)}
              </dd>
            {/if}
          </dl>
        </section>

        <!-- Storage card. -->
        <section aria-labelledby="crawler-website-detail-storage" class="flex flex-col gap-2">
          <h3
            id="crawler-website-detail-storage"
            class="text-muted-foreground text-xs tracking-wide uppercase"
          >
            {m.crawler_website_detail_section_storage()}
          </h3>
          <dl class="grid grid-cols-[max-content_1fr] items-baseline gap-x-3 gap-y-1.5">
            <dt class="text-muted-foreground text-sm">
              {m.crawler_tenant_website_inventory_column_size()}
            </dt>
            <dd class="text-sm tabular-nums">
              {detailCandidateView.size > 0
                ? formatCrawlerScheduledIndexedSize(detailCandidateView.size)
                : "—"}
            </dd>
          </dl>
        </section>

        <!--
          Action footer. Each button hands off to an existing dialog so
          the audit + tenancy guarantees from the original surfaces apply
          unchanged. Reset + Abort are conditional — hiding instead of
          disabling keeps the affordance honest.
          -->
        <section
          aria-labelledby="crawler-website-detail-actions"
          class="border-border flex flex-col gap-2 border-t pt-4"
        >
          <h3
            id="crawler-website-detail-actions"
            class="text-muted-foreground text-xs tracking-wide uppercase"
          >
            {m.crawler_website_detail_section_actions()}
          </h3>
          <Button
            variant="outline"
            size="sm"
            onclick={() => {
              if (detailCandidateView) openRetryDialogForInventoryItem(detailCandidateView);
            }}
            disabled={retryingWebsiteId !== null}
          >
            {m.crawler_website_detail_action_retry()}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onclick={() => {
              if (detailCandidateView) openIntervalDialogForInventoryItem(detailCandidateView);
            }}
            disabled={savingIntervalWebsiteId !== null}
          >
            {m.crawler_website_detail_action_interval()}
          </Button>
          {#if detailCandidateView.failure_state !== null}
            <Button
              variant="outline"
              size="sm"
              onclick={() => {
                if (detailCandidateView)
                  openCircuitResetDialogForInventoryItem(detailCandidateView);
              }}
              disabled={resettingCircuitWebsiteId !== null}
            >
              {m.crawler_website_detail_action_reset()}
            </Button>
          {/if}
          {#if detailActiveJob !== null}
            <Button
              variant="destructive"
              size="sm"
              onclick={() => {
                if (detailCandidateView) openAbortDialogForInventoryItem(detailCandidateView);
              }}
              disabled={abortingJobId !== null}
            >
              <CircleX data-icon="inline-start" aria-hidden="true" />
              {m.crawler_website_detail_action_abort()}
            </Button>
          {/if}
        </section>
      </div>
    {/if}
  </Sheet.Content>
</Sheet.Root>

<AlertDialog.Root bind:open={abortDialogOpen}>
  <AlertDialog.Content>
    {#if abortCandidate}
      {@const candidateIsRunning = isCrawlerActiveInventoryItemRunning(abortCandidate)}
      {@const candidateWebsite = getCrawlerActiveInventoryWebsiteLabel(abortCandidate)}
      <AlertDialog.Header>
        <AlertDialog.Title>
          {candidateIsRunning
            ? m.crawler_abort_dialog_title_running()
            : m.crawler_abort_dialog_title_queued()}
        </AlertDialog.Title>
        <AlertDialog.Description>
          {candidateIsRunning
            ? m.crawler_abort_dialog_description_running({ website: candidateWebsite })
            : m.crawler_abort_dialog_description_queued({ website: candidateWebsite })}
        </AlertDialog.Description>
      </AlertDialog.Header>
      <AlertDialog.Footer>
        <AlertDialog.Cancel disabled={abortingJobId !== null}>{m.cancel()}</AlertDialog.Cancel>
        <AlertDialog.Action
          variant="destructive"
          disabled={abortingJobId !== null}
          onclick={() => void handleAbortCrawl()}
        >
          {abortingJobId !== null
            ? m.crawler_abort_button_busy()
            : candidateIsRunning
              ? m.crawler_abort_dialog_confirm_running()
              : m.crawler_abort_dialog_confirm_queued()}
        </AlertDialog.Action>
      </AlertDialog.Footer>
    {/if}
  </AlertDialog.Content>
</AlertDialog.Root>

<AlertDialog.Root bind:open={circuitResetDialogOpen}>
  <AlertDialog.Content>
    {#if circuitResetCandidate}
      {@const resetCopy = getCrawlerCircuitBreakerResetCopy(
        circuitResetCandidate
      ) satisfies CrawlerCircuitBreakerResetCopy}
      <AlertDialog.Header>
        <AlertDialog.Title>{resetCopy.dialogTitle}</AlertDialog.Title>
        <AlertDialog.Description>
          {resetCopy.dialogDescription}
        </AlertDialog.Description>
      </AlertDialog.Header>
      {#if resetCopy.followupHint}
        <Alert.Root>
          <TriangleAlert aria-hidden="true" />
          <Alert.Description>{resetCopy.followupHint}</Alert.Description>
        </Alert.Root>
      {/if}
      <AlertDialog.Footer>
        <AlertDialog.Cancel disabled={resettingCircuitWebsiteId !== null}>
          {resetCopy.cancelLabel}
        </AlertDialog.Cancel>
        <AlertDialog.Action
          disabled={resettingCircuitWebsiteId !== null}
          onclick={() => void handleResetCircuitBreaker()}
        >
          {resettingCircuitWebsiteId !== null ? resetCopy.busyLabel : resetCopy.confirmLabel}
        </AlertDialog.Action>
      </AlertDialog.Footer>
    {/if}
  </AlertDialog.Content>
</AlertDialog.Root>

<AlertDialog.Root bind:open={intervalDialogOpen}>
  <AlertDialog.Content>
    {#if intervalCandidate}
      {@const intervalCurrent = intervalCandidate.update_interval as CrawlerUpdateInterval}
      {@const intervalWebsite =
        intervalCandidate.website_name?.trim() ||
        intervalCandidate.website_url ||
        m.crawler_active_inventory_unknown_website({
          id: intervalCandidate.website_id.slice(0, 8)
        })}
      {@const intervalSaving = savingIntervalWebsiteId !== null}
      {@const pausing = isPausingTransition(intervalCurrent, intervalDraft)}
      {@const resuming = isResumingTransition(intervalCurrent, intervalDraft)}
      <AlertDialog.Header>
        <AlertDialog.Title>{m.crawler_update_interval_dialog_title()}</AlertDialog.Title>
        <AlertDialog.Description>
          {m.crawler_update_interval_dialog_description({ website: intervalWebsite })}
        </AlertDialog.Description>
      </AlertDialog.Header>
      <div class="flex flex-col gap-3 py-2">
        <p class="text-muted-foreground text-xs">
          {m.crawler_update_interval_current({
            interval: getCrawlerUpdateIntervalLabel(intervalCurrent)
          })}
        </p>
        <Select.Root
          type="single"
          value={intervalDraft}
          onValueChange={(value) => {
            if (value) intervalDraft = value as CrawlerUpdateInterval;
          }}
          disabled={intervalSaving}
        >
          <Select.Trigger aria-label={m.crawler_update_interval_dialog_label()}>
            {getCrawlerUpdateIntervalLabel(intervalDraft)}
          </Select.Trigger>
          <Select.Content>
            {#each CRAWLER_UPDATE_INTERVAL_OPTIONS as option (option)}
              <Select.Item value={option}>
                {getCrawlerUpdateIntervalLabel(option)}
              </Select.Item>
            {/each}
          </Select.Content>
        </Select.Root>
      </div>
      <AlertDialog.Footer>
        <AlertDialog.Cancel disabled={intervalSaving}>{m.cancel()}</AlertDialog.Cancel>
        <AlertDialog.Action
          disabled={intervalSaving || intervalDraft === intervalCurrent}
          onclick={() => void handleSaveUpdateInterval()}
        >
          {intervalSaving
            ? m.crawler_update_interval_dialog_busy()
            : pausing
              ? m.crawler_update_interval_dialog_confirm_pause()
              : resuming
                ? m.crawler_update_interval_dialog_confirm_resume()
                : m.crawler_update_interval_dialog_confirm()}
        </AlertDialog.Action>
      </AlertDialog.Footer>
    {/if}
  </AlertDialog.Content>
</AlertDialog.Root>

<AlertDialog.Root bind:open={retryDialogOpen}>
  <AlertDialog.Content>
    {#if retryCandidate}
      {@const retryWebsite =
        retryCandidate.website_name?.trim() ||
        retryCandidate.website_url ||
        m.crawler_active_inventory_unknown_website({
          id: retryCandidate.website_id.slice(0, 8)
        })}
      {@const retrySaving = retryingWebsiteId !== null}
      <AlertDialog.Header>
        <AlertDialog.Title>{m.crawler_retry_dialog_title()}</AlertDialog.Title>
        <AlertDialog.Description>
          {m.crawler_retry_dialog_description({ website: retryWebsite })}
        </AlertDialog.Description>
      </AlertDialog.Header>
      <AlertDialog.Footer>
        <AlertDialog.Cancel disabled={retrySaving}>{m.cancel()}</AlertDialog.Cancel>
        <AlertDialog.Action disabled={retrySaving} onclick={() => void handleRetryCrawl()}>
          {retrySaving ? m.crawler_retry_button_busy() : m.crawler_retry_dialog_confirm()}
        </AlertDialog.Action>
      </AlertDialog.Footer>
    {/if}
  </AlertDialog.Content>
</AlertDialog.Root>
