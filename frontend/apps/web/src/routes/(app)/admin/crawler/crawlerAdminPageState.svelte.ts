/*
 * Copyright (c) 2026 Sundsvalls Kommun
 *
 * Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).
 * See the LICENSE file at the repository root for the full license text.
 */

import { invalidate } from "$app/navigation";
import { toast } from "$lib/components/toast";
import { toastError } from "$lib/core/errors";
import type { Intric } from "@intric/intric-js";
import { m } from "$lib/paraglide/messages";
import {
  getCrawlerAbortConflictMessage,
  isCrawlerActiveInventoryItemRunning,
  type CrawlerActiveInventoryItem
} from "$lib/features/admin/crawlerActiveInventory";
import {
  canSubmitCrawlerBulkIntervalSelection,
  type CrawlerBulkIntervalResponse
} from "$lib/features/admin/crawlerBulkInterval";
import {
  getCrawlerCircuitBreakerResetCopy,
  type CrawlerCircuitBreakerResetCandidate
} from "$lib/features/admin/crawlerCircuitBreakerReset";
import type { CrawlerTenantFailureInventoryItem } from "$lib/features/admin/crawlerFailureInventory";
import {
  getCrawlerTenantWebsiteInventoryDisplayName,
  type CrawlerTenantWebsiteInventoryItem
} from "$lib/features/admin/crawlerTenantWebsiteInventory";
import type { CrawlerUpdateInterval } from "$lib/features/admin/crawlerUpdateInterval";

type RetryCandidate = {
  website_id: string;
  website_name: string | null;
  website_url: string | null;
};

type IntervalEditCandidate = {
  website_id: string;
  website_name: string | null;
  website_url: string | null;
  update_interval: CrawlerUpdateInterval;
};

export type DetailRef = {
  set: (item: CrawlerTenantWebsiteInventoryItem | null) => void;
};

async function invalidateAfterWebsiteDelete(): Promise<void> {
  await Promise.all([
    invalidate("admin:crawler-tenant-website-inventory"),
    invalidate("admin:crawler-failure-inventory"),
    invalidate("admin:crawler-active-inventory"),
    invalidate("admin:crawler-scheduled"),
    invalidate("admin:crawler-website-processing")
  ]);
}

async function invalidateAfterAbort(): Promise<void> {
  await Promise.all([
    invalidate("admin:crawler-active-inventory"),
    invalidate("admin:crawler-recent-failures")
  ]);
}

async function invalidateAfterCircuitReset(): Promise<void> {
  await invalidate("admin:crawler-failure-inventory");
}

async function invalidateAfterIntervalChange(
  options: { includeInventory: boolean } = { includeInventory: false }
): Promise<void> {
  const keys = [
    "admin:crawler-failure-inventory",
    "admin:crawler-scheduled",
    "admin:crawler-website-processing",
    "admin:crawler-active-inventory"
  ];
  if (options.includeInventory) keys.unshift("admin:crawler-tenant-website-inventory");
  await Promise.all(keys.map((key) => invalidate(key)));
}

async function invalidateAfterRetry(): Promise<void> {
  await Promise.all([
    invalidate("admin:crawler-active-inventory"),
    invalidate("admin:crawler-failure-inventory"),
    invalidate("admin:crawler-recent-failures")
  ]);
}

async function invalidateAfterBulkInterval(): Promise<void> {
  await Promise.all([
    invalidate("admin:crawler-tenant-website-inventory"),
    invalidate("admin:crawler-scheduled"),
    invalidate("admin:crawler-failure-inventory"),
    invalidate("admin:crawler-website-processing")
  ]);
}

export type CrawlerSelectionRef = {
  values: () => Iterable<string>;
  size: () => number;
  delete: (id: string) => void;
};

export function createCrawlerDialogState(intric: Intric, detailRef: DetailRef) {
  let deleteDialogOpen = $state(false);
  let deleteCandidate = $state<CrawlerTenantWebsiteInventoryItem | null>(null);
  let deleteConfirmInput = $state("");
  let deletingWebsiteId = $state<string | null>(null);

  let abortDialogOpen = $state(false);
  let abortCandidate = $state<CrawlerActiveInventoryItem | null>(null);
  let abortingJobId = $state<string | null>(null);

  let circuitResetDialogOpen = $state(false);
  let circuitResetCandidate = $state<CrawlerCircuitBreakerResetCandidate | null>(null);
  let resettingCircuitWebsiteId = $state<string | null>(null);

  let intervalDialogOpen = $state(false);
  let intervalCandidate = $state<IntervalEditCandidate | null>(null);
  let intervalDraft = $state<CrawlerUpdateInterval>("never");
  let savingIntervalWebsiteId = $state<string | null>(null);

  let retryDialogOpen = $state(false);
  let retryCandidate = $state<RetryCandidate | null>(null);
  let retryingWebsiteId = $state<string | null>(null);

  function openDelete(item: CrawlerTenantWebsiteInventoryItem) {
    detailRef.set(null);
    deleteCandidate = item;
    deleteConfirmInput = "";
    deleteDialogOpen = true;
  }

  function openAbort(item: CrawlerActiveInventoryItem) {
    detailRef.set(null);
    abortCandidate = item;
    abortDialogOpen = true;
  }

  function openCircuitReset(item: CrawlerCircuitBreakerResetCandidate) {
    circuitResetCandidate = item;
    circuitResetDialogOpen = true;
  }

  function openRetry(item: RetryCandidate) {
    detailRef.set(null);
    retryCandidate = { ...item };
    retryDialogOpen = true;
  }

  function openInterval(item: IntervalEditCandidate) {
    intervalCandidate = item;
    intervalDraft = item.update_interval;
    intervalDialogOpen = true;
  }

  function openIntervalForFailureItem(item: CrawlerTenantFailureInventoryItem) {
    openInterval({
      website_id: item.website_id,
      website_name: item.website_name,
      website_url: item.website_url,
      update_interval: item.update_interval as CrawlerUpdateInterval
    });
  }

  function openIntervalForActiveItem(item: CrawlerActiveInventoryItem) {
    if (item.update_interval === null || item.website_id === null) return;
    openInterval({
      website_id: item.website_id,
      website_name: item.website_name,
      website_url: null,
      update_interval: item.update_interval as CrawlerUpdateInterval
    });
  }

  function openIntervalForInventoryItem(item: CrawlerTenantWebsiteInventoryItem) {
    detailRef.set(null);
    openInterval({
      website_id: item.website_id,
      website_name: item.name,
      website_url: item.url,
      update_interval: item.update_interval as CrawlerUpdateInterval
    });
  }

  function openCircuitResetForInventoryItem(item: CrawlerTenantWebsiteInventoryItem) {
    if (item.failure_state === null) return;
    detailRef.set(null);
    openCircuitReset({
      website_id: item.website_id,
      website_url: item.url,
      website_name: item.name,
      space_id: item.space_id,
      space_name: item.space_name,
      owner_user_id: item.owner_user_id,
      owner_email: item.owner_email,
      state: item.failure_state,
      update_interval: item.update_interval as CrawlerUpdateInterval,
      consecutive_failures: item.consecutive_failures,
      next_retry_at: item.next_retry_at,
      last_crawled_at: item.last_crawled_at,
      updated_at: item.last_crawled_at ?? item.created_at,
      latest_failure_outcome_code: null,
      latest_failure_at: null
    });
  }

  function openRetryForInventoryItem(item: CrawlerTenantWebsiteInventoryItem) {
    openRetry({
      website_id: item.website_id,
      website_name: item.name,
      website_url: item.url
    });
  }

  function websiteLabel(
    name: string | null | undefined,
    url: string | null | undefined,
    id: string
  ): string {
    return (
      name?.trim() || url || m.crawler_active_inventory_unknown_website({ id: id.slice(0, 8) })
    );
  }

  async function confirmDelete() {
    const candidate = deleteCandidate;
    if (candidate === null) return;
    if (deleteConfirmInput.trim() !== candidate.url.trim()) return;

    deletingWebsiteId = candidate.website_id;
    try {
      await intric.crawlerAdmin.deleteWebsite(candidate.website_id);
      toast.success(
        m.crawler_website_delete_success({
          website: getCrawlerTenantWebsiteInventoryDisplayName(candidate)
        })
      );
      deleteDialogOpen = false;
      deleteCandidate = null;
      deleteConfirmInput = "";
      detailRef.set(null);
      await invalidateAfterWebsiteDelete();
    } catch (error) {
      toastError(error, m.crawler_website_delete_failed());
    } finally {
      deletingWebsiteId = null;
    }
  }

  async function confirmAbort() {
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
      await invalidateAfterAbort();
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

  async function confirmCircuitReset() {
    const candidate = circuitResetCandidate;
    if (candidate === null) return;
    resettingCircuitWebsiteId = candidate.website_id;
    const copy = getCrawlerCircuitBreakerResetCopy(candidate);
    try {
      await intric.crawlerAdmin.resetCircuitBreaker(candidate.website_id);
      circuitResetDialogOpen = false;
      circuitResetCandidate = null;
      toast.success(copy.successMessage);
      await invalidateAfterCircuitReset();
    } catch (error) {
      toastError(error, copy.failureMessage);
    } finally {
      resettingCircuitWebsiteId = null;
    }
  }

  async function confirmInterval() {
    const candidate = intervalCandidate;
    if (candidate === null) return;
    const currentInterval = candidate.update_interval;
    const nextInterval = intervalDraft;
    if (currentInterval === nextInterval) {
      intervalDialogOpen = false;
      intervalCandidate = null;
      return;
    }
    savingIntervalWebsiteId = candidate.website_id;
    const label = websiteLabel(candidate.website_name, candidate.website_url, candidate.website_id);
    try {
      await intric.crawlerAdmin.setUpdateInterval(candidate.website_id, nextInterval);
      intervalDialogOpen = false;
      intervalCandidate = null;
      toast.success(m.crawler_update_interval_success({ website: label }));
      await invalidateAfterIntervalChange();
    } catch (error) {
      toastError(error, m.crawler_update_interval_failed());
    } finally {
      savingIntervalWebsiteId = null;
    }
  }

  async function confirmRetry() {
    const candidate = retryCandidate;
    if (candidate === null) return;
    retryingWebsiteId = candidate.website_id;
    const label = websiteLabel(candidate.website_name, candidate.website_url, candidate.website_id);
    try {
      await intric.crawlerAdmin.retryCrawl(candidate.website_id);
      retryDialogOpen = false;
      retryCandidate = null;
      toast.success(m.crawler_retry_success({ website: label }));
      await invalidateAfterRetry();
    } catch (error) {
      toastError(error, m.crawler_retry_failed());
    } finally {
      retryingWebsiteId = null;
    }
  }

  async function inlineSaveInterval(
    websiteId: string,
    newInterval: CrawlerUpdateInterval,
    detailLabel: string
  ) {
    savingIntervalWebsiteId = websiteId;
    try {
      await intric.crawlerAdmin.setUpdateInterval(websiteId, newInterval);
      toast.success(m.crawler_update_interval_success({ website: detailLabel }));
      await invalidateAfterIntervalChange({ includeInventory: true });
    } catch (error) {
      toastError(error, m.crawler_update_interval_failed());
    } finally {
      savingIntervalWebsiteId = null;
    }
  }

  const deleteGroup = {
    get open() {
      return deleteDialogOpen;
    },
    set open(v: boolean) {
      deleteDialogOpen = v;
    },
    get candidate() {
      return deleteCandidate;
    },
    get confirmInput() {
      return deleteConfirmInput;
    },
    set confirmInput(v: string) {
      deleteConfirmInput = v;
    },
    get busy() {
      return deletingWebsiteId;
    },
    openFor: openDelete,
    confirm: confirmDelete
  };

  const abortGroup = {
    get open() {
      return abortDialogOpen;
    },
    set open(v: boolean) {
      abortDialogOpen = v;
    },
    get candidate() {
      return abortCandidate;
    },
    get busy() {
      return abortingJobId;
    },
    openFor: openAbort,
    confirm: confirmAbort
  };

  const circuitResetGroup = {
    get open() {
      return circuitResetDialogOpen;
    },
    set open(v: boolean) {
      circuitResetDialogOpen = v;
    },
    get candidate() {
      return circuitResetCandidate;
    },
    get busy() {
      return resettingCircuitWebsiteId;
    },
    openFor: openCircuitReset,
    openForInventoryItem: openCircuitResetForInventoryItem,
    confirm: confirmCircuitReset
  };

  const intervalGroup = {
    get open() {
      return intervalDialogOpen;
    },
    set open(v: boolean) {
      intervalDialogOpen = v;
    },
    get candidate() {
      return intervalCandidate;
    },
    get draft() {
      return intervalDraft;
    },
    set draft(v: CrawlerUpdateInterval) {
      intervalDraft = v;
    },
    get busy() {
      return savingIntervalWebsiteId;
    },
    openForFailureItem: openIntervalForFailureItem,
    openForActiveItem: openIntervalForActiveItem,
    openForInventoryItem: openIntervalForInventoryItem,
    confirm: confirmInterval,
    inlineSave: inlineSaveInterval
  };

  const retryGroup = {
    get open() {
      return retryDialogOpen;
    },
    set open(v: boolean) {
      retryDialogOpen = v;
    },
    get candidate() {
      return retryCandidate;
    },
    get busy() {
      return retryingWebsiteId;
    },
    openFor: openRetry,
    openForInventoryItem: openRetryForInventoryItem,
    confirm: confirmRetry
  };

  return {
    delete: deleteGroup,
    abort: abortGroup,
    circuitReset: circuitResetGroup,
    interval: intervalGroup,
    retry: retryGroup
  };
}

export type CrawlerDialogState = ReturnType<typeof createCrawlerDialogState>;

export function createBulkIntervalState(intric: Intric, selection: CrawlerSelectionRef) {
  let dialogOpen = $state<boolean>(false);
  let draft = $state<CrawlerUpdateInterval>("never");
  let applying = $state<boolean>(false);
  let lastResult = $state<CrawlerBulkIntervalResponse | null>(null);

  function open() {
    lastResult = null;
    draft = "never";
    dialogOpen = true;
  }

  function close() {
    if (applying) return;
    dialogOpen = false;
    lastResult = null;
  }

  async function apply() {
    const ids = Array.from(selection.values());
    if (!canSubmitCrawlerBulkIntervalSelection({ selected_count: ids.length, interval: draft })) {
      return;
    }
    applying = true;
    try {
      const result = await intric.crawlerAdmin.bulkSetUpdateInterval(ids, draft);
      lastResult = result;
      for (const applied of result.applied) {
        selection.delete(applied.website_id);
      }
      if (result.failed.length === 0) {
        toast.success(
          m.crawler_bulk_interval_toast_success({ applied: String(result.applied.length) })
        );
        setTimeout(() => {
          if (lastResult === result) {
            dialogOpen = false;
            lastResult = null;
          }
        }, 600);
      } else {
        toast.error(
          m.crawler_bulk_interval_toast_partial({
            applied: String(result.applied.length),
            failed: String(result.failed.length)
          })
        );
      }
      await invalidateAfterBulkInterval();
    } catch (error) {
      toastError(error, m.crawler_bulk_interval_toast_error());
    } finally {
      applying = false;
    }
  }

  return {
    get dialogOpen() {
      return dialogOpen;
    },
    set dialogOpen(v: boolean) {
      dialogOpen = v;
    },
    get draft() {
      return draft;
    },
    set draft(v: CrawlerUpdateInterval) {
      draft = v;
    },
    get applying() {
      return applying;
    },
    get lastResult() {
      return lastResult;
    },
    open,
    close,
    apply
  };
}

export type BulkIntervalState = ReturnType<typeof createBulkIntervalState>;
