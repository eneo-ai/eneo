<!--
  Copyright (c) 2026 Sundsvalls Kommun

  Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).
  See the LICENSE file at the repository root for the full license text.
-->

<script lang="ts">
  import { untrack } from "svelte";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Separator } from "$lib/components/ui/separator/index.js";
  import { CircleX, ExternalLink, FileSearch } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import { getLocale, localizeHref } from "$lib/paraglide/runtime";
  import type { Intric } from "@intric/intric-js";
  import type { CrawlerActiveInventoryItem } from "$lib/features/admin/crawlerActiveInventory";
  import {
    createCrawlerRelativeTimeFormatter,
    formatCrawlerRelativeTime
  } from "$lib/features/admin/crawlerRelativeTime";
  import {
    getCrawlerWebsiteProcessingLatestRunEmbeddingUsageLabel,
    getCrawlerWebsiteProcessingLatestRunModelLabel,
    getCrawlerWebsiteProcessingLatestRunProviderLabel,
    getCrawlerWebsiteProcessingLatestRunUsageSourceLabel,
    type CrawlerTenantWebsiteProcessingAggregateItem
  } from "$lib/features/admin/crawlerWebsiteProcessing";
  import { formatCrawlerScheduledIndexedSize } from "$lib/features/admin/crawlerScheduledAggregate";
  import {
    getCrawlerTenantWebsiteInventoryDisplayName,
    getCrawlerTenantWebsiteInventoryOwnerLabel,
    getCrawlerTenantWebsiteInventorySpaceLabel,
    getCrawlerTenantWebsiteInventoryStatusLabel,
    getWebsiteDetailDialogActionVisibility,
    type CrawlerTenantWebsiteInventoryItem,
    type CrawlerTenantWebsiteInventoryResponse
  } from "$lib/features/admin/crawlerTenantWebsiteInventory";
  import {
    CRAWLER_UPDATE_INTERVAL_OPTIONS,
    getCrawlerUpdateIntervalLabel,
    type CrawlerUpdateInterval
  } from "$lib/features/admin/crawlerUpdateInterval";

  let {
    candidate = null,
    visibleInventory = null,
    intric,
    abortingJobId = null,
    retryingWebsiteId = null,
    savingIntervalWebsiteId = null,
    resettingCircuitWebsiteId = null,
    deletingWebsiteId = null,
    onClose,
    onOpenAbortDialog,
    onOpenRetryDialog,
    onSaveInterval,
    onOpenCircuitResetDialog,
    onOpenDeleteDialog
  }: {
    candidate: CrawlerTenantWebsiteInventoryItem | null;
    visibleInventory: CrawlerTenantWebsiteInventoryResponse | null;
    intric: Intric;
    abortingJobId?: string | null;
    retryingWebsiteId?: string | null;
    savingIntervalWebsiteId?: string | null;
    resettingCircuitWebsiteId?: string | null;
    deletingWebsiteId?: string | null;
    onClose: () => void;
    onOpenAbortDialog: (item: CrawlerActiveInventoryItem) => void;
    onOpenRetryDialog: (item: CrawlerTenantWebsiteInventoryItem) => void;
    // Inline schedule edit: caller persists the new interval and the
    // dialog stays open (no second AlertDialog). Returns void; toast
    // + invalidate is the caller's responsibility.
    onSaveInterval: (websiteId: string, newInterval: CrawlerUpdateInterval) => Promise<void>;
    onOpenCircuitResetDialog: (item: CrawlerTenantWebsiteInventoryItem) => void;
    onOpenDeleteDialog: (item: CrawlerTenantWebsiteInventoryItem) => void;
  } = $props();

  // Inline schedule edit state. Writable derived: re-evaluates from
  // the candidate whenever the operator opens a different row, but
  // user mutation (via Select) overrides until the source changes
  // again. This is the canonical Svelte 5 pattern instead of
  // $state + $effect (which the linter rightly rejects as redundant
  // for this use case).
  let intervalDraft = $derived<CrawlerUpdateInterval | null>(
    (candidate?.update_interval as CrawlerUpdateInterval | undefined) ?? null
  );
  const intervalIsDirty = $derived(
    candidate !== null &&
      intervalDraft !== null &&
      intervalDraft !== (candidate.update_interval as CrawlerUpdateInterval)
  );

  async function handleSaveInterval() {
    if (candidate === null || intervalDraft === null || !intervalIsDirty) return;
    await onSaveInterval(candidate.website_id, intervalDraft);
  }

  function resetIntervalDraft() {
    if (candidate === null) return;
    intervalDraft = candidate.update_interval as CrawlerUpdateInterval;
  }

  // The dialog is "controlled" via candidate. Untracked snapshot of
  // `candidate` prevents the onOpenChange→onClose loop when the
  // parent already nulled the candidate (e.g. via Esc → onClose).
  function handleOpenChange(open: boolean) {
    if (open) return;
    const stillHasCandidate = untrack(() => candidate !== null);
    if (stillHasCandidate) onClose();
  }

  // The candidate may go stale if the parent's inventory refreshes
  // while the drawer is open — re-resolve against the visible
  // inventory so post-retry updates land in the drawer without
  // re-opening. Falls back to the click snapshot if the row left the
  // visible page.
  const candidateView = $derived<CrawlerTenantWebsiteInventoryItem | null>(
    candidate === null
      ? null
      : (visibleInventory?.items.find((item) => item.website_id === candidate?.website_id) ??
          candidate)
  );

  const relativeFormatter = createCrawlerRelativeTimeFormatter();

  const createdRelative = $derived<string | null>(
    candidateView?.created_at
      ? formatCrawlerRelativeTime(relativeFormatter, candidateView.created_at)
      : null
  );
  const lastCrawledRelative = $derived<string | null>(
    candidateView?.last_crawled_at
      ? formatCrawlerRelativeTime(relativeFormatter, candidateView.last_crawled_at)
      : null
  );
  const nextRetryRelative = $derived<string | null>(
    candidateView?.next_retry_at
      ? formatCrawlerRelativeTime(relativeFormatter, candidateView.next_retry_at)
      : null
  );

  // Active jobs can live outside the current Drift page, so the dialog
  // asks the active-inventory endpoint for the selected website instead
  // of trusting page-local state. The cancellation guard prevents an
  // older response from overwriting a newer candidate's result.
  let activeJob = $state<CrawlerActiveInventoryItem | null>(null);
  $effect(() => {
    const current = candidate;
    if (current === null) {
      activeJob = null;
      return;
    }
    const target = current.website_id;
    let cancelled = false;
    intric.crawlerAdmin
      .activeInventory({ website_id: target, limit: 1 })
      .then((response) => {
        if (cancelled) return;
        const matching = response.items.find((item) => item.is_abortable);
        activeJob = matching ?? null;
      })
      .catch(() => {
        if (cancelled) return;
        activeJob = null;
      });
    return () => {
      cancelled = true;
    };
  });

  let processingStats = $state<CrawlerTenantWebsiteProcessingAggregateItem | null>(null);
  let processingStatsLoadFailed = $state(false);
  $effect(() => {
    const current = candidate;
    if (current === null) {
      processingStats = null;
      processingStatsLoadFailed = false;
      return;
    }
    const target = current.website_id;
    let cancelled = false;
    intric.crawlerAdmin
      .websiteProcessingAggregate({ website_id: target, days: 7, limit: 1 })
      .then((response) => {
        if (cancelled) return;
        processingStats = response.items[0] ?? null;
        processingStatsLoadFailed = false;
      })
      .catch(() => {
        if (cancelled) return;
        processingStats = null;
        processingStatsLoadFailed = true;
      });
    return () => {
      cancelled = true;
    };
  });

  function tenantWebsiteInventoryRowStatusClass(item: CrawlerTenantWebsiteInventoryItem): string {
    if (item.failure_state === "AUTO_DISABLED") {
      return "border-destructive/35 bg-destructive/8 text-destructive";
    }
    if (item.failure_state === "BACKED_OFF") {
      return "border-caution/40 bg-caution/8 text-caution";
    }
    return "border-positive-default/40 bg-positive-dimmer text-positive-stronger";
  }

  function formatDateTime(value: string): string {
    return new Date(value).toLocaleString(getLocale(), {
      dateStyle: "medium",
      timeStyle: "short"
    });
  }

  function handleAbort() {
    const item = candidateView;
    const job = activeJob;
    if (item === null || job === null) return;
    onOpenAbortDialog(job);
  }

  function handleRetry() {
    const item = candidateView;
    if (item === null) return;
    onOpenRetryDialog(item);
  }

  function handleCircuitReset() {
    const item = candidateView;
    if (item === null || item.failure_state === null) return;
    onOpenCircuitResetDialog(item);
  }

  function handleDelete() {
    const item = candidateView;
    if (item === null) return;
    onOpenDeleteDialog(item);
  }

  // Button visibility has one pure owner so the dialog and unit tests
  // cannot drift when active-job or failure-state rules change.
  const actionVisibility = $derived(
    getWebsiteDetailDialogActionVisibility({
      candidate: candidateView,
      hasActiveJob: activeJob !== null
    })
  );
</script>

<Dialog.Root open={candidate !== null} onOpenChange={handleOpenChange}>
  <Dialog.Content class="gap-0 p-0 sm:max-w-2xl">
    {#if candidateView}
      {@const display = getCrawlerTenantWebsiteInventoryDisplayName(candidateView)}
      {@const hasUrl = candidateView.url && candidateView.url !== display}
      <div class="border-border space-y-1.5 border-b py-4 pr-12 pl-6">
        <div class="flex flex-wrap items-start gap-x-3 gap-y-1.5">
          <Dialog.Title class="text-foreground min-w-0 flex-1 truncate text-base font-semibold">
            {display}
          </Dialog.Title>
          {#if !hasUrl && candidateView.url}
            <!-- eslint-disable svelte/no-navigation-without-resolve -- external crawler website URL -->
            <a
              href={candidateView.url}
              target="_blank"
              rel="noopener noreferrer"
              class="text-muted-foreground hover:text-accent-default focus-visible:ring-ring/50 mt-1 inline-flex shrink-0 items-center rounded-sm focus-visible:ring-2 focus-visible:outline-none"
              title={m.crawler_website_detail_open_external()}
            >
              <ExternalLink class="size-3.5" aria-hidden="true" />
              <span class="sr-only">{m.crawler_website_detail_open_external()}</span>
            </a>
            <!-- eslint-enable svelte/no-navigation-without-resolve -->
          {/if}
          <div class="flex shrink-0 items-center gap-1.5">
            <Badge variant="outline" class={tenantWebsiteInventoryRowStatusClass(candidateView)}>
              {getCrawlerTenantWebsiteInventoryStatusLabel(candidateView)}
            </Badge>
            {#if activeJob !== null}
              <Badge
                variant="outline"
                class="border-accent-default/35 text-accent-default tabular-nums"
              >
                {m.crawler_website_detail_active_job()}
              </Badge>
            {/if}
          </div>
        </div>
        {#if hasUrl}
          <Dialog.Description class="flex items-center gap-1.5">
            <span class="text-muted-foreground truncate text-xs" title={candidateView.url}>
              {candidateView.url}
            </span>
            <!-- eslint-disable svelte/no-navigation-without-resolve -- external crawler website URL -->
            <a
              href={candidateView.url}
              target="_blank"
              rel="noopener noreferrer"
              class="text-accent-default hover:text-accent-strongest inline-flex shrink-0 items-center gap-0.5 text-xs hover:underline"
            >
              <ExternalLink class="size-3" aria-hidden="true" />
              <span class="sr-only">{m.crawler_website_detail_open_external()}</span>
            </a>
            <!-- eslint-enable svelte/no-navigation-without-resolve -->
          </Dialog.Description>
        {/if}
      </div>

      <div class="space-y-5 px-6 py-5">
        <div class="grid grid-cols-1 gap-x-8 gap-y-5 sm:grid-cols-2">
          <section aria-labelledby="crawler-website-detail-config" class="space-y-2.5">
            <h3
              id="crawler-website-detail-config"
              class="text-muted-foreground text-[10px] font-medium tracking-wider uppercase"
            >
              {m.crawler_website_detail_section_config()}
            </h3>
            <dl class="grid grid-cols-[max-content_1fr] items-baseline gap-x-3 gap-y-1.5 text-sm">
              <dt class="text-muted-foreground">
                {m.crawler_website_detail_field_crawl_type()}
              </dt>
              <dd class="text-foreground">
                {candidateView.crawl_type === "sitemap" ? m.sitemap_based_crawl() : m.basic_crawl()}
              </dd>
              <dt class="text-muted-foreground">
                {m.crawler_website_detail_field_interval()}
              </dt>
              <dd class="text-foreground">
                <div class="flex flex-wrap items-center gap-2">
                  <Select.Root
                    type="single"
                    value={intervalDraft ?? candidateView.update_interval}
                    onValueChange={(value) => {
                      if (value) intervalDraft = value as CrawlerUpdateInterval;
                    }}
                    disabled={savingIntervalWebsiteId !== null}
                  >
                    <Select.Trigger
                      class="h-7 w-44 px-2 text-sm"
                      aria-label={m.crawler_website_detail_field_interval()}
                    >
                      {getCrawlerUpdateIntervalLabel(
                        (intervalDraft ?? candidateView.update_interval) as CrawlerUpdateInterval
                      )}
                    </Select.Trigger>
                    <Select.Content>
                      {#each CRAWLER_UPDATE_INTERVAL_OPTIONS as option (option)}
                        <Select.Item value={option}>
                          {getCrawlerUpdateIntervalLabel(option)}
                        </Select.Item>
                      {/each}
                    </Select.Content>
                  </Select.Root>
                  {#if intervalIsDirty}
                    <Button
                      size="sm"
                      onclick={() => void handleSaveInterval()}
                      disabled={savingIntervalWebsiteId !== null}
                    >
                      {savingIntervalWebsiteId !== null
                        ? m.crawler_website_detail_save_interval_busy()
                        : m.crawler_website_detail_save_interval()}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onclick={resetIntervalDraft}
                      disabled={savingIntervalWebsiteId !== null}
                    >
                      {m.crawler_website_detail_cancel_interval()}
                    </Button>
                  {/if}
                </div>
              </dd>
              <dt class="text-muted-foreground">
                {m.crawler_website_detail_field_download_files()}
              </dt>
              <dd class="text-foreground">
                {candidateView.download_files
                  ? m.crawler_website_detail_value_enabled()
                  : m.crawler_website_detail_value_disabled()}
              </dd>
              <dt class="text-muted-foreground">
                {m.crawler_website_detail_field_http_auth()}
              </dt>
              <dd class="text-foreground">
                {#if candidateView.requires_http_auth}
                  {m.crawler_website_detail_value_enabled()}
                  {#if candidateView.http_auth_username}
                    <span class="text-muted-foreground">
                      ({candidateView.http_auth_username})
                    </span>
                  {/if}
                {:else}
                  {m.crawler_website_detail_value_disabled()}
                {/if}
              </dd>
            </dl>
          </section>

          <section aria-labelledby="crawler-website-detail-ownership" class="space-y-2.5">
            <h3
              id="crawler-website-detail-ownership"
              class="text-muted-foreground text-[10px] font-medium tracking-wider uppercase"
            >
              {m.crawler_website_detail_section_ownership()}
            </h3>
            <dl class="grid grid-cols-[max-content_1fr] items-baseline gap-x-3 gap-y-1.5 text-sm">
              <dt class="text-muted-foreground">
                {m.crawler_website_detail_field_space()}
              </dt>
              <dd
                class="text-foreground truncate"
                title={getCrawlerTenantWebsiteInventorySpaceLabel(candidateView)}
              >
                <span class="truncate">
                  {getCrawlerTenantWebsiteInventorySpaceLabel(candidateView)}
                </span>
              </dd>
              <dt class="text-muted-foreground">
                {m.crawler_website_detail_field_owner()}
              </dt>
              <dd
                class="text-foreground truncate"
                title={getCrawlerTenantWebsiteInventoryOwnerLabel(candidateView)}
              >
                {#if candidateView.owner_email}
                  <!-- eslint-disable svelte/no-navigation-without-resolve -- localizeHref handles routing -->
                  <a
                    href={localizeHref(
                      `/admin/users?tab=active&search=${encodeURIComponent(candidateView.owner_email)}`
                    )}
                    class="text-foreground hover:text-accent-default inline-flex items-center gap-1 truncate hover:underline"
                    aria-label={m.crawler_website_detail_open_owner_user()}
                  >
                    <span class="truncate">{candidateView.owner_email}</span>
                  </a>
                  <!-- eslint-enable svelte/no-navigation-without-resolve -->
                {:else}
                  {getCrawlerTenantWebsiteInventoryOwnerLabel(candidateView)}
                {/if}
              </dd>
              {#if candidateView.collection_name}
                <dt class="text-muted-foreground">
                  {m.crawler_website_detail_field_collection()}
                </dt>
                <dd class="text-foreground truncate" title={candidateView.collection_name}>
                  <span class="truncate">{candidateView.collection_name}</span>
                </dd>
              {/if}
              <dt class="text-muted-foreground">
                {m.crawler_website_detail_field_created()}
              </dt>
              <dd class="text-foreground">
                <time datetime={candidateView.created_at} class="block tabular-nums">
                  {formatDateTime(candidateView.created_at)}
                </time>
                {#if createdRelative}
                  <p class="text-muted-foreground text-[11px]">
                    {createdRelative}
                  </p>
                {/if}
              </dd>
            </dl>
          </section>
        </div>

        <Separator />

        <section aria-labelledby="crawler-website-detail-activity" class="space-y-2.5">
          <div class="flex items-baseline justify-between gap-3">
            <h3
              id="crawler-website-detail-activity"
              class="text-muted-foreground text-[10px] font-medium tracking-wider uppercase"
            >
              {m.crawler_website_detail_section_activity()}
            </h3>
            {#if candidateView.url}
              <!-- eslint-disable svelte/no-navigation-without-resolve -- localizeHref handles routing -->
              <a
                href={localizeHref(
                  `/admin/audit-logs?tab=logs&search=${encodeURIComponent(candidateView.url)}`
                )}
                class="text-accent-default hover:text-accent-strongest inline-flex items-center gap-1 text-xs hover:underline"
                aria-label={m.crawler_website_detail_view_audit_logs_aria()}
              >
                <FileSearch class="size-3" aria-hidden="true" />
                <span>{m.crawler_website_detail_view_audit_logs()}</span>
              </a>
              <!-- eslint-enable svelte/no-navigation-without-resolve -->
            {/if}
          </div>
          <div class="flex flex-wrap gap-x-8 gap-y-3 text-sm">
            <div class="min-w-36 space-y-0.5">
              <p class="text-muted-foreground text-xs">
                {m.crawler_website_detail_field_last_crawled()}
              </p>
              {#if candidateView.last_crawled_at}
                <time
                  datetime={candidateView.last_crawled_at}
                  class="text-foreground block tabular-nums"
                >
                  {formatDateTime(candidateView.last_crawled_at)}
                </time>
                {#if lastCrawledRelative}
                  <p class="text-muted-foreground text-[11px]">
                    {lastCrawledRelative}
                  </p>
                {/if}
              {:else}
                <p class="text-foreground tabular-nums">—</p>
              {/if}
            </div>
            <div class="min-w-36 space-y-0.5">
              <p class="text-muted-foreground text-xs">
                {m.crawler_tenant_website_inventory_column_size()}
              </p>
              <p class="text-foreground tabular-nums">
                {candidateView.size > 0
                  ? formatCrawlerScheduledIndexedSize(candidateView.size)
                  : "—"}
              </p>
            </div>
            {#if candidateView.failure_state !== null && candidateView.consecutive_failures > 0}
              <div class="min-w-36 space-y-0.5">
                <p class="text-muted-foreground text-xs">
                  {m.crawler_website_detail_field_consecutive_failures()}
                </p>
                <p class="text-foreground tabular-nums">
                  {candidateView.consecutive_failures}
                </p>
              </div>
            {/if}
            {#if candidateView.next_retry_at}
              <div class="min-w-36 space-y-0.5">
                <p class="text-muted-foreground text-xs">
                  {m.crawler_website_detail_field_next_retry()}
                </p>
                <time
                  datetime={candidateView.next_retry_at}
                  class="text-foreground block tabular-nums"
                >
                  {formatDateTime(candidateView.next_retry_at)}
                </time>
                {#if nextRetryRelative}
                  <p class="text-muted-foreground text-[11px]">
                    {nextRetryRelative}
                  </p>
                {/if}
              </div>
            {/if}
          </div>
        </section>

        <Separator />

        <section aria-labelledby="crawler-website-detail-cost-model" class="space-y-2.5">
          <h3
            id="crawler-website-detail-cost-model"
            class="text-muted-foreground text-[10px] font-medium tracking-wider uppercase"
          >
            {m.crawler_website_detail_section_cost_model()}
          </h3>
          <dl class="grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2">
            <div class="space-y-0.5">
              <dt class="text-muted-foreground text-xs">
                {m.crawler_website_detail_field_embedding_model()}
              </dt>
              <dd
                class="text-foreground truncate"
                title={processingStats
                  ? getCrawlerWebsiteProcessingLatestRunModelLabel(processingStats)
                  : undefined}
              >
                {#if processingStatsLoadFailed}
                  {m.crawler_website_processing_embedding_model_unknown()}
                {:else if processingStats}
                  {getCrawlerWebsiteProcessingLatestRunModelLabel(processingStats)}
                {:else}
                  —
                {/if}
              </dd>
            </div>
            <div class="space-y-0.5">
              <dt class="text-muted-foreground text-xs">
                {m.crawler_website_detail_field_embedding_provider()}
              </dt>
              <dd
                class="text-foreground truncate"
                title={processingStats
                  ? getCrawlerWebsiteProcessingLatestRunProviderLabel(processingStats)
                  : undefined}
              >
                {#if processingStatsLoadFailed}
                  {m.crawler_website_processing_embedding_model_unknown()}
                {:else if processingStats}
                  {getCrawlerWebsiteProcessingLatestRunProviderLabel(processingStats)}
                {:else}
                  —
                {/if}
              </dd>
            </div>
            <div class="space-y-0.5">
              <dt class="text-muted-foreground text-xs">
                {m.crawler_website_detail_field_embedding_last_run_usage()}
              </dt>
              <dd class="text-foreground tabular-nums">
                {#if processingStatsLoadFailed}
                  {m.crawler_website_processing_embedding_usage_unknown()}
                {:else if processingStats}
                  {getCrawlerWebsiteProcessingLatestRunEmbeddingUsageLabel(processingStats)}
                {:else}
                  —
                {/if}
              </dd>
            </div>
            <div class="space-y-0.5">
              <dt class="text-muted-foreground text-xs">
                {m.crawler_website_detail_field_embedding_usage_source()}
              </dt>
              <dd class="text-foreground">
                {#if processingStatsLoadFailed}
                  {m.crawler_website_processing_embedding_usage_source_legacy()}
                {:else if processingStats}
                  {getCrawlerWebsiteProcessingLatestRunUsageSourceLabel(processingStats)}
                {:else}
                  —
                {/if}
              </dd>
            </div>
          </dl>
        </section>
      </div>

      <!-- Plain div, not Dialog.Footer: shadcn footer's `-mx-4 -mb-4` assumes a `p-4` parent, but Content here is `p-0`. -->
      <div
        class="border-border flex flex-wrap items-center justify-between gap-2 rounded-b-xl border-t px-6 py-4"
      >
        <div class="flex flex-wrap items-center gap-2">
          {#if actionVisibility.retry}
            <Button
              variant="default"
              size="sm"
              onclick={handleRetry}
              disabled={retryingWebsiteId !== null}
              data-testid="crawler-website-detail-action-retry"
            >
              {m.crawler_website_detail_action_retry()}
            </Button>
          {/if}
          {#if actionVisibility.reset}
            <Button
              variant="outline"
              size="sm"
              onclick={handleCircuitReset}
              disabled={resettingCircuitWebsiteId !== null}
              data-testid="crawler-website-detail-action-reset"
            >
              {m.crawler_website_detail_action_reset()}
            </Button>
          {/if}
        </div>
        <div class="flex flex-wrap items-center gap-2">
          {#if actionVisibility.abort}
            <Button
              variant="destructive"
              size="sm"
              onclick={handleAbort}
              disabled={abortingJobId !== null}
              data-testid="crawler-website-detail-action-abort"
            >
              <CircleX data-icon="inline-start" aria-hidden="true" />
              {m.crawler_website_detail_action_abort()}
            </Button>
          {/if}
          {#if actionVisibility.delete}
            <Button
              variant="destructive"
              size="sm"
              onclick={handleDelete}
              disabled={deletingWebsiteId !== null}
              data-testid="crawler-website-detail-action-delete"
            >
              {m.crawler_website_detail_action_delete()}
            </Button>
          {/if}
        </div>
      </div>
    {/if}
  </Dialog.Content>
</Dialog.Root>
