/*
 * Copyright (c) 2026 Sundsvalls Kommun
 *
 * Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).
 * See the LICENSE file at the repository root for the full license text.
 */

/**
 * Filter + pagination state for the Aktivitet (crawler activity) tab.
 *
 * Kept separate from the page-wide dialog state so the toolbar (search +
 * sort + time-window + focus filters + page size + offset) has one
 * canonical source of truth. The tab component reads getters; toolbar
 * controls invoke the named transition methods; the `refresh()` method
 * re-fetches against the backend `/admin/crawler/website-processing`
 * endpoint with whatever the current state holds.
 *
 * `intric` is captured at construction so the tab component only needs
 * to mount the state once and pass `intric` exactly once. The state
 * survives tab switches within the same admin page mount.
 *
 * Codex review (gpt-5.5 / effort xhigh) called out the risk of letting
 * Aktivitet state live inline in the tab component once debounce + sort
 * + 3 chips + page-size + skeleton + dual empty states all land. This
 * module is the agreed sibling to `crawlerAdminPageState.svelte.ts`.
 */

import { invalidate } from "$app/navigation";
import { toastError } from "$lib/core/errors";
import {
  CRAWLER_WEBSITE_PROCESSING_DEFAULTS,
  type CrawlerTenantWebsiteProcessingAggregateResponse,
  type CrawlerWebsiteProcessingPageSize,
  type CrawlerWebsiteProcessingSort,
  type CrawlerWebsiteProcessingTimeWindow,
  offsetFromCrawlerWebsiteProcessingPage
} from "$lib/features/admin/crawlerWebsiteProcessing";
import { m } from "$lib/paraglide/messages";
import type { Intric } from "@intric/intric-js";

export type CrawlerActivityFilters = {
  failuresOnly: boolean;
  lowRetentionOnly: boolean;
  sourceSkipDriftOnly: boolean;
};

export type CrawlerActivityState = ReturnType<typeof createCrawlerActivityState>;

export function createCrawlerActivityState(
  intric: Intric,
  initial: {
    response: CrawlerTenantWebsiteProcessingAggregateResponse | null;
    loadFailed: boolean;
  }
) {
  let visible = $state<CrawlerTenantWebsiteProcessingAggregateResponse | null>(initial.response);
  let loadFailed = $state<boolean>(initial.loadFailed);
  let busy = $state<boolean>(false);

  let search = $state<string>("");
  let days = $state<CrawlerWebsiteProcessingTimeWindow>(CRAWLER_WEBSITE_PROCESSING_DEFAULTS.days);
  let sort = $state<CrawlerWebsiteProcessingSort>(CRAWLER_WEBSITE_PROCESSING_DEFAULTS.sort);
  let pageSize = $state<CrawlerWebsiteProcessingPageSize>(
    CRAWLER_WEBSITE_PROCESSING_DEFAULTS.limit as CrawlerWebsiteProcessingPageSize
  );
  let page = $state<number>(1);
  let failuresOnly = $state<boolean>(false);
  let lowRetentionOnly = $state<boolean>(false);
  let sourceSkipDriftOnly = $state<boolean>(false);

  // Per-keystroke fetch would stampede the backend; the toolbar wires
  // the input through `setSearch` which debounces via a timer. Keeping
  // the timer in this module rather than the component means swapping
  // it for `useDebounce` or moving to URL-driven state later is a
  // one-file change.
  let searchDebounce: ReturnType<typeof setTimeout> | null = null;
  const SEARCH_DEBOUNCE_MS = 250;

  async function refresh(options: { resetPage?: boolean } = {}) {
    if (options.resetPage) page = 1;
    busy = true;
    const offset = offsetFromCrawlerWebsiteProcessingPage(page, pageSize);
    const params: {
      days: number;
      limit: number;
      offset: number;
      sort: CrawlerWebsiteProcessingSort;
      failures_only?: boolean;
      low_retention_only?: boolean;
      source_skip_drift_only?: boolean;
      search?: string;
    } = {
      days,
      limit: pageSize,
      offset,
      sort
    };
    if (failuresOnly) params.failures_only = true;
    if (lowRetentionOnly) params.low_retention_only = true;
    if (sourceSkipDriftOnly) params.source_skip_drift_only = true;
    const trimmedSearch = search.trim();
    if (trimmedSearch.length > 0) params.search = trimmedSearch;

    try {
      const response = await intric.crawlerAdmin.websiteProcessingAggregate(params);
      visible = response;
      loadFailed = false;
      await invalidate("admin:crawler-website-processing");
    } catch (error) {
      loadFailed = true;
      toastError(error, m.crawler_website_processing_load_error());
    } finally {
      busy = false;
    }
  }

  function setSearch(next: string) {
    search = next;
    if (searchDebounce !== null) clearTimeout(searchDebounce);
    searchDebounce = setTimeout(() => {
      searchDebounce = null;
      void refresh({ resetPage: true });
    }, SEARCH_DEBOUNCE_MS);
  }

  function clearSearch() {
    if (searchDebounce !== null) {
      clearTimeout(searchDebounce);
      searchDebounce = null;
    }
    if (search === "") return;
    search = "";
    void refresh({ resetPage: true });
  }

  function setDays(next: CrawlerWebsiteProcessingTimeWindow) {
    if (next === days) return;
    days = next;
    void refresh({ resetPage: true });
  }

  function setSort(next: CrawlerWebsiteProcessingSort) {
    if (next === sort) return;
    sort = next;
    void refresh({ resetPage: true });
  }

  function setPageSize(next: CrawlerWebsiteProcessingPageSize) {
    if (next === pageSize) return;
    pageSize = next;
    void refresh({ resetPage: true });
  }

  function setPage(next: number) {
    if (next === page || next < 1) return;
    page = next;
    void refresh({});
  }

  function setFailuresOnly(next: boolean) {
    if (next === failuresOnly) return;
    failuresOnly = next;
    void refresh({ resetPage: true });
  }

  function setLowRetentionOnly(next: boolean) {
    if (next === lowRetentionOnly) return;
    lowRetentionOnly = next;
    void refresh({ resetPage: true });
  }

  function setSourceSkipDriftOnly(next: boolean) {
    if (next === sourceSkipDriftOnly) return;
    sourceSkipDriftOnly = next;
    void refresh({ resetPage: true });
  }

  function clearFilters() {
    if (!failuresOnly && !lowRetentionOnly && !sourceSkipDriftOnly && search.trim().length === 0) {
      return;
    }
    if (searchDebounce !== null) {
      clearTimeout(searchDebounce);
      searchDebounce = null;
    }
    failuresOnly = false;
    lowRetentionOnly = false;
    sourceSkipDriftOnly = false;
    search = "";
    void refresh({ resetPage: true });
  }

  return {
    get visible() {
      return visible;
    },
    get loadFailed() {
      return loadFailed;
    },
    get busy() {
      return busy;
    },
    get search() {
      return search;
    },
    get days() {
      return days;
    },
    get sort() {
      return sort;
    },
    get pageSize() {
      return pageSize;
    },
    get page() {
      return page;
    },
    get filters(): CrawlerActivityFilters {
      return {
        failuresOnly,
        lowRetentionOnly,
        sourceSkipDriftOnly
      };
    },
    get activeFilterCount(): number {
      let count = 0;
      if (failuresOnly) count += 1;
      if (lowRetentionOnly) count += 1;
      if (sourceSkipDriftOnly) count += 1;
      if (search.trim().length > 0) count += 1;
      return count;
    },
    setSearch,
    clearSearch,
    setDays,
    setSort,
    setPageSize,
    setPage,
    setFailuresOnly,
    setLowRetentionOnly,
    setSourceSkipDriftOnly,
    clearFilters,
    refresh
  };
}
