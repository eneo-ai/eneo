<!--
  Copyright (c) 2026 Sundsvalls Kommun

  Licensed under the MIT License.
-->

<!--
  Webbplatser detail Dialog. Centered `@intric/ui` Dialog matching
  WebsiteEditor.svelte's identity. Reads from the candidate row passed
  in by the parent (Webbplatser tab) and re-resolves it against the
  visible inventory each render so an operator-triggered refresh
  propagates updates without re-opening. Each action button hands off
  to an existing AlertDialog flow in the parent via callback props —
  keeps this slice free of new mutation endpoints + audit emissions.

  The component is a "controlled" surface: when `candidate` is set to a
  non-null inventory row the dialog opens; setting it back to null
  closes the dialog. The parent owns the candidate state.

  Active-job lookup uses the V2-B server-side filter on
  `/admin/crawler/active?website_id=...` so the abort affordance is
  correct regardless of which page of the active inventory was loaded
  when the operator opened the drawer.
-->

<script lang="ts">
  import { onMount, untrack } from "svelte";
  import { writable } from "svelte/store";
  import { Dialog } from "@intric/ui";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { CircleX } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import type { Intric } from "@intric/intric-js";
  import type { CrawlerActiveInventoryItem } from "$lib/features/admin/crawlerActiveInventory";
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
  import { getCrawlerUpdateIntervalLabel } from "$lib/features/admin/crawlerUpdateInterval";

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
    onOpenIntervalDialog,
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
    onOpenIntervalDialog: (item: CrawlerTenantWebsiteInventoryItem) => void;
    onOpenCircuitResetDialog: (item: CrawlerTenantWebsiteInventoryItem) => void;
    onOpenDeleteDialog: (item: CrawlerTenantWebsiteInventoryItem) => void;
  } = $props();

  // Open state is derived from the candidate being non-null; we hold
  // it as a `Writable<boolean>` so the @intric/ui Dialog's
  // `openController` prop can flip it via the Esc key / close button.
  // When the store flips to false on user action, we notify the
  // parent so it can null out the candidate.
  const openStore = writable(false);
  $effect(() => {
    openStore.set(candidate !== null);
  });
  onMount(() => {
    const unsubscribe = openStore.subscribe((open) => {
      if (!open) {
        // The candidate may still be non-null when the store flips
        // (e.g., Esc key). Untracked check + callback so the parent
        // doesn't re-fire its own close handler in a loop.
        const stillHasCandidate = untrack(() => candidate !== null);
        if (stillHasCandidate) onClose();
      }
    });
    return unsubscribe;
  });

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

  // Authoritative active-job lookup: V2-B server-side filter on the
  // active inventory. Without this the abort affordance falsely hid
  // when the queued job lived on an unloaded page of the active
  // inventory. We re-fetch whenever the candidate's website_id
  // changes; cancellation guard prevents an out-of-order response
  // from overwriting a newer candidate's result.
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

  function formatRelativeOrAbsolute(value: string | null): string {
    if (!value) return "—";
    return formatDateTime(value);
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

  function handleInterval() {
    const item = candidateView;
    if (item === null) return;
    onOpenIntervalDialog(item);
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

  // Visibility derives from the same pure helper that the V2-E
  // unit-test exercises against 7 quadrants. Wiring through this
  // helper guarantees the rendered UI cannot disagree with the
  // test-asserted spec.
  const actionVisibility = $derived(
    getWebsiteDetailDialogActionVisibility({
      candidate: candidateView,
      hasActiveJob: activeJob !== null
    })
  );
</script>

<Dialog.Root openController={openStore}>
  <Dialog.Content width="medium">
    {#if candidateView}
      {@const display = getCrawlerTenantWebsiteInventoryDisplayName(candidateView)}
      <Dialog.Title>{display}</Dialog.Title>
      {#if candidateView.url && candidateView.url !== display}
        <Dialog.Description>
          <span class="text-foreground break-words">{candidateView.url}</span>
          <button
            type="button"
            class="text-accent-default ml-1 text-xs hover:underline"
            onclick={() => {
              if (candidateView?.url) {
                window.open(candidateView.url, "_blank", "noopener,noreferrer");
              }
            }}
          >
            {m.crawler_website_detail_open_external()}
          </button>
        </Dialog.Description>
      {/if}

      <Dialog.Section>
        <div class="flex flex-col gap-5 p-4">
          <div class="flex flex-wrap items-center gap-2">
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

          <section aria-labelledby="crawler-website-detail-config" class="flex flex-col gap-2">
            <h3
              id="crawler-website-detail-config"
              class="text-muted-foreground text-xs tracking-wide uppercase"
            >
              {m.crawler_website_detail_section_config()}
            </h3>
            <dl class="grid grid-cols-[max-content_1fr] items-baseline gap-x-3 gap-y-1.5">
              <dt class="text-muted-foreground text-sm">
                {m.crawler_website_detail_field_crawl_type()}
              </dt>
              <dd class="text-sm">
                {candidateView.crawl_type === "sitemap" ? m.sitemap_based_crawl() : m.basic_crawl()}
              </dd>
              <dt class="text-muted-foreground text-sm">
                {m.crawler_website_detail_field_interval()}
              </dt>
              <dd class="text-sm">
                {getCrawlerUpdateIntervalLabel(candidateView.update_interval)}
              </dd>
              <dt class="text-muted-foreground text-sm">
                {m.crawler_website_detail_field_download_files()}
              </dt>
              <dd class="text-sm">
                {candidateView.download_files
                  ? m.crawler_website_detail_value_enabled()
                  : m.crawler_website_detail_value_disabled()}
              </dd>
              <dt class="text-muted-foreground text-sm">
                {m.crawler_website_detail_field_http_auth()}
              </dt>
              <dd class="text-sm">
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
                {getCrawlerTenantWebsiteInventorySpaceLabel(candidateView)}
              </dd>
              <dt class="text-muted-foreground text-sm">
                {m.crawler_website_detail_field_owner()}
              </dt>
              <dd class="text-sm">
                {getCrawlerTenantWebsiteInventoryOwnerLabel(candidateView)}
              </dd>
              <dt class="text-muted-foreground text-sm">
                {m.crawler_website_detail_field_created()}
              </dt>
              <dd class="text-sm tabular-nums">
                {formatDateTime(candidateView.created_at)}
              </dd>
            </dl>
          </section>

          <section aria-labelledby="crawler-website-detail-activity" class="flex flex-col gap-2">
            <h3
              id="crawler-website-detail-activity"
              class="text-muted-foreground text-xs tracking-wide uppercase"
            >
              {m.crawler_website_detail_section_activity()}
            </h3>
            <dl class="grid grid-cols-[max-content_1fr] items-baseline gap-x-3 gap-y-1.5">
              <dt class="text-muted-foreground text-sm">
                {m.crawler_website_detail_field_last_crawled()}
              </dt>
              <dd class="text-sm tabular-nums">
                {formatRelativeOrAbsolute(candidateView.last_crawled_at)}
              </dd>
              <dt class="text-muted-foreground text-sm">
                {m.crawler_tenant_website_inventory_column_size()}
              </dt>
              <dd class="text-sm tabular-nums">
                {candidateView.size > 0
                  ? formatCrawlerScheduledIndexedSize(candidateView.size)
                  : "—"}
              </dd>
              {#if candidateView.failure_state !== null && candidateView.consecutive_failures > 0}
                <dt class="text-muted-foreground text-sm">
                  {m.crawler_website_detail_field_consecutive_failures()}
                </dt>
                <dd class="text-sm tabular-nums">
                  {candidateView.consecutive_failures}
                </dd>
              {/if}
              {#if candidateView.next_retry_at}
                <dt class="text-muted-foreground text-sm">
                  {m.crawler_website_detail_field_next_retry()}
                </dt>
                <dd class="text-sm tabular-nums">
                  {formatDateTime(candidateView.next_retry_at)}
                </dd>
              {/if}
            </dl>
          </section>

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
            {#if actionVisibility.retry}
              <Button
                variant="outline"
                size="sm"
                onclick={handleRetry}
                disabled={retryingWebsiteId !== null}
                data-testid="crawler-website-detail-action-retry"
              >
                {m.crawler_website_detail_action_retry()}
              </Button>
            {/if}
            {#if actionVisibility.interval}
              <Button
                variant="outline"
                size="sm"
                onclick={handleInterval}
                disabled={savingIntervalWebsiteId !== null}
                data-testid="crawler-website-detail-action-interval"
              >
                {m.crawler_website_detail_action_interval()}
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
          </section>
        </div>
      </Dialog.Section>
    {/if}
  </Dialog.Content>
</Dialog.Root>
