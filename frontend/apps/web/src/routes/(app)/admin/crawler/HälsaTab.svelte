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
  import * as Pagination from "$lib/components/ui/pagination/index.js";
  import { ChevronRight, Clock3, RotateCcw, ShieldCheck, TriangleAlert } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import {
    getCrawlerCircuitBreakerResetCopy,
    type CrawlerCircuitBreakerResetCandidate
  } from "$lib/features/admin/crawlerCircuitBreakerReset";
  import {
    CRAWLER_FAILURE_CLUSTERS_PAGE_SIZE,
    getCrawlerFailureClusterAttributionLabel,
    getCrawlerFailureClusterLatestLabel,
    getCrawlerFailureClusterOccurrenceLabel,
    getCrawlerFailureClusterOutcomeLabel,
    getCrawlerFailureClusterWebsiteLabel,
    getCrawlerFailureClusterWorkLabel,
    type CrawlerFailureClustersResponse
  } from "$lib/features/admin/crawlerFailureClusters";
  import {
    getCrawlerFailureInventoryAttributionLabel,
    getCrawlerFailureInventoryFailureLabel,
    getCrawlerFailureInventoryLatestFailureLabel,
    getCrawlerFailureInventoryLatestFailureTimeLabel,
    getCrawlerFailureInventoryNextStepLabel,
    getCrawlerFailureInventoryStateLabel,
    getCrawlerFailureInventoryStateTooltip,
    getCrawlerFailureInventoryTotalLabel,
    getCrawlerFailureInventoryWebsiteLabel,
    type CrawlerTenantFailureInventoryResponse
  } from "$lib/features/admin/crawlerFailureInventory";
  import { crawlerFailureStateBadgeClass } from "$lib/features/admin/crawlerPresentation";
  import {
    createCrawlerRelativeTimeFormatter,
    formatCrawlerRelativeTime
  } from "$lib/features/admin/crawlerRelativeTime";
  import type { CrawlerTenantWebsiteInventoryItem } from "$lib/features/admin/crawlerTenantWebsiteInventory";
  import EmptyState from "./EmptyState.svelte";

  type ResolvedRowLabel = {
    label: string;
    inventoryItem: CrawlerTenantWebsiteInventoryItem | null;
  };

  type PaginatedFeed<TResponse> = {
    visible: TResponse | null;
    loadFailed: boolean;
    windowDays: number;
    page: number;
    busy: boolean;
    onChangePage: (next: number) => void;
  };

  type MutationState = {
    retryingWebsiteId: string | null;
    savingIntervalWebsiteId: string | null;
    resettingCircuitWebsiteId: string | null;
  };

  type Props = {
    failureInventory: CrawlerTenantFailureInventoryResponse | null;
    failureInventoryLoadFailed: boolean;
    failureClusters: PaginatedFeed<CrawlerFailureClustersResponse>;
    mutationState: MutationState;
    resolveRowLabel: (row: { website_id: string; website_name: string | null }) => ResolvedRowLabel;
    onOpenWebsiteDetail: (item: CrawlerTenantWebsiteInventoryItem) => void;
    onOpenRetryDialog: (item: CrawlerCircuitBreakerResetCandidate) => void;
    onOpenIntervalDialog: (item: CrawlerCircuitBreakerResetCandidate) => void;
    onOpenCircuitResetDialog: (item: CrawlerCircuitBreakerResetCandidate) => void;
  };

  const {
    failureInventory,
    failureInventoryLoadFailed,
    failureClusters,
    mutationState,
    resolveRowLabel,
    onOpenWebsiteDetail,
    onOpenRetryDialog,
    onOpenIntervalDialog,
    onOpenCircuitResetDialog
  }: Props = $props();

  // One formatter instance per mount keeps i18n / Intl.RelativeTimeFormat
  // construction off the render path. Shared between the Webbplatser
  // detail dialog and Aktivitet rows; same convention here.
  const clusterRelativeTimeFormatter = createCrawlerRelativeTimeFormatter();
</script>

<Card.Root class="mb-10" aria-labelledby="crawler-failure-inventory-title">
  <Card.Header>
    <div class="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
      <div class="flex min-w-0 flex-col gap-1">
        <h2 id="crawler-failure-inventory-title" class="text-base leading-snug font-semibold">
          {m.crawler_failure_inventory_title()}
        </h2>
        <Card.Description>{m.crawler_failure_inventory_description()}</Card.Description>
      </div>
      {#if failureInventory}
        <Badge variant="outline" class="shrink-0 tabular-nums">
          {getCrawlerFailureInventoryTotalLabel(failureInventory)}
        </Badge>
      {/if}
    </div>
  </Card.Header>
  <Card.Content class="pt-0">
    {#if failureInventoryLoadFailed}
      <Alert.Root variant="destructive">
        <TriangleAlert aria-hidden="true" />
        <Alert.Description>{m.crawler_failure_inventory_load_error()}</Alert.Description>
      </Alert.Root>
    {:else if !failureInventory || failureInventory.items.length === 0}
      <EmptyState
        title={m.crawler_empty_failure_inventory_title()}
        description={m.crawler_empty_failure_inventory_description()}
      >
        {#snippet icon()}
          <ShieldCheck class="size-5" />
        {/snippet}
      </EmptyState>
    {:else}
      <div class="divide-border divide-y" aria-label={m.crawler_failure_inventory_table_caption()}>
        <div
          class="text-muted-foreground hidden grid-cols-[minmax(0,1.8fr)_minmax(11rem,.75fr)_minmax(0,1.1fr)_minmax(0,1fr)] gap-4 px-2 pb-2 text-xs font-medium tracking-wide uppercase lg:grid"
          aria-hidden="true"
        >
          <span>{m.crawler_failure_inventory_column_website()}</span>
          <span>{m.crawler_failure_inventory_column_state()}</span>
          <span>{m.crawler_failure_inventory_column_latest_failure()}</span>
          <span>{m.crawler_failure_inventory_column_next_step()}</span>
        </div>
        {#each failureInventory.items as failureState (failureState.website_id)}
          {@const resetCopy = getCrawlerCircuitBreakerResetCopy(failureState)}
          {@const isResettingThis =
            mutationState.resettingCircuitWebsiteId === failureState.website_id}
          {@const latestFailureTime =
            getCrawlerFailureInventoryLatestFailureTimeLabel(failureState)}
          {@const resolved = resolveRowLabel({
            website_id: failureState.website_id,
            website_name: failureState.website_name
          })}
          <article
            class="grid grid-cols-1 gap-3 px-2 py-4 lg:grid-cols-[minmax(0,1.8fr)_minmax(11rem,.75fr)_minmax(0,1.1fr)_minmax(0,1fr)]"
          >
            <div class="min-w-0">
              <p
                class="truncate text-sm font-medium"
                title={getCrawlerFailureInventoryWebsiteLabel(failureState)}
              >
                {getCrawlerFailureInventoryWebsiteLabel(failureState)}
              </p>
              <p class="text-muted-foreground mt-1 truncate text-xs">
                {getCrawlerFailureInventoryAttributionLabel(failureState)}
              </p>
              <p class="text-muted-foreground mt-1 text-xs">
                {getCrawlerFailureInventoryFailureLabel(failureState)}
              </p>
            </div>

            <div class="flex items-start">
              <Badge
                variant="outline"
                class={crawlerFailureStateBadgeClass(failureState.state)}
                title={getCrawlerFailureInventoryStateTooltip(failureState)}
              >
                {getCrawlerFailureInventoryStateLabel(failureState)}
              </Badge>
            </div>

            <div class="min-w-0 text-sm">
              <p
                class="truncate font-medium"
                title={getCrawlerFailureInventoryLatestFailureLabel(failureState)}
              >
                {getCrawlerFailureInventoryLatestFailureLabel(failureState)}
              </p>
              {#if latestFailureTime}
                <p class="text-muted-foreground mt-1 flex items-center gap-1 text-xs tabular-nums">
                  <Clock3 class="size-3.5" aria-hidden="true" />
                  {latestFailureTime}
                </p>
              {/if}
            </div>

            <p class="text-muted-foreground text-sm">
              {getCrawlerFailureInventoryNextStepLabel(failureState)}
            </p>

            <div
              class="flex flex-wrap items-center justify-start gap-2 lg:col-span-4 lg:justify-end"
            >
              {#if resolved.inventoryItem}
                <Button
                  variant="ghost"
                  size="sm"
                  onclick={() =>
                    resolved.inventoryItem && onOpenWebsiteDetail(resolved.inventoryItem)}
                >
                  {m.crawler_inventory_row_action_view_detail()}
                </Button>
              {/if}
              <Button
                variant="ghost"
                size="sm"
                aria-label={m.crawler_retry_button_aria({
                  website: getCrawlerFailureInventoryWebsiteLabel(failureState)
                })}
                disabled={mutationState.retryingWebsiteId !== null}
                onclick={() => onOpenRetryDialog(failureState)}
              >
                {mutationState.retryingWebsiteId === failureState.website_id
                  ? m.crawler_retry_button_busy()
                  : m.crawler_retry_button()}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                aria-label={m.crawler_update_interval_button_aria({
                  website: getCrawlerFailureInventoryWebsiteLabel(failureState)
                })}
                disabled={mutationState.savingIntervalWebsiteId !== null}
                onclick={() => onOpenIntervalDialog(failureState)}
              >
                {mutationState.savingIntervalWebsiteId === failureState.website_id
                  ? m.crawler_update_interval_dialog_busy()
                  : m.crawler_update_interval_button()}
              </Button>
              <Button
                variant="outline"
                size="sm"
                aria-label={resetCopy.ariaLabel}
                disabled={mutationState.resettingCircuitWebsiteId !== null}
                onclick={() => onOpenCircuitResetDialog(failureState)}
              >
                {isResettingThis
                  ? resetCopy.busyLabel
                  : failureState.state === "AUTO_DISABLED"
                    ? m.crawler_circuit_breaker_reset_button_paused()
                    : m.crawler_circuit_breaker_reset_button_backed_off()}
              </Button>
            </div>
          </article>
        {/each}
      </div>
    {/if}
  </Card.Content>
</Card.Root>

<Card.Root aria-labelledby="crawler-failure-clusters-title">
  <Card.Header>
    <div class="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
      <div class="flex min-w-0 flex-col gap-1">
        <h2 id="crawler-failure-clusters-title" class="text-base leading-snug font-semibold">
          {m.crawler_failure_clusters_title()}
        </h2>
        <Card.Description>
          {m.crawler_failure_clusters_description({ days: failureClusters.windowDays })}
        </Card.Description>
      </div>
      {#if failureClusters.visible}
        <Badge variant="outline" class="shrink-0 tabular-nums">
          {m.crawler_failure_clusters_count({
            shown: failureClusters.visible.items.length,
            total: failureClusters.visible.total
          })}
        </Badge>
      {/if}
    </div>
  </Card.Header>
  <Card.Content class="pt-0">
    {#if failureClusters.loadFailed}
      <Alert.Root variant="destructive">
        <TriangleAlert aria-hidden="true" />
        <Alert.Description>{m.crawler_failure_clusters_load_error()}</Alert.Description>
      </Alert.Root>
    {:else if !failureClusters.visible || failureClusters.visible.items.length === 0}
      <EmptyState
        title={m.crawler_empty_failure_clusters_title()}
        description={m.crawler_empty_failure_clusters_description()}
      >
        {#snippet icon()}
          <ShieldCheck class="size-5" />
        {/snippet}
      </EmptyState>
    {:else}
      <div class="divide-border divide-y" aria-label={m.crawler_failure_clusters_table_caption()}>
        <div
          class="text-muted-foreground hidden grid-cols-[minmax(0,1.7fr)_minmax(0,1.2fr)_minmax(0,.9fr)_minmax(0,.85fr)_auto] gap-4 px-2 pb-2 text-xs font-medium tracking-wide uppercase lg:grid"
          aria-hidden="true"
        >
          <span>{m.crawler_failure_clusters_column_pattern()}</span>
          <span>{m.crawler_failure_clusters_column_website()}</span>
          <span>{m.crawler_failure_clusters_column_work()}</span>
          <span>{m.crawler_failure_clusters_column_latest()}</span>
          <span class="text-right">{m.crawler_failure_inventory_column_action()}</span>
        </div>
        {#each failureClusters.visible.items as cluster (`${cluster.website_id}:${cluster.outcome_code}`)}
          {@const resolved = resolveRowLabel({
            website_id: cluster.website_id,
            website_name: cluster.website_name
          })}
          {@const clusterLatestRelative = formatCrawlerRelativeTime(
            clusterRelativeTimeFormatter,
            cluster.latest_failed_at
          )}
          <article
            class="grid grid-cols-1 items-start gap-3 px-2 py-4 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1.2fr)_minmax(0,.9fr)_minmax(0,.85fr)_auto]"
          >
            <div class="flex min-w-0 flex-col gap-1">
              <div class="flex min-w-0 flex-wrap items-center gap-2">
                <p
                  class="min-w-0 truncate text-sm font-semibold"
                  title={getCrawlerFailureClusterOutcomeLabel(cluster)}
                >
                  {getCrawlerFailureClusterOutcomeLabel(cluster)}
                </p>
                {#if cluster.watchdog_occurrences > 0}
                  <Badge
                    variant="outline"
                    class="border-caution/40 bg-caution/8 text-caution shrink-0 gap-1 font-normal"
                    title={m.crawler_failure_cluster_watchdog_tooltip()}
                  >
                    <RotateCcw class="size-3.5" aria-hidden="true" />
                    {m.crawler_failure_cluster_watchdog_badge()}
                  </Badge>
                {/if}
              </div>
              <p class="text-muted-foreground text-xs">
                {getCrawlerFailureClusterOccurrenceLabel(cluster)}
              </p>
            </div>
            <div class="min-w-0">
              <p
                class="truncate text-sm font-medium"
                title={getCrawlerFailureClusterWebsiteLabel(cluster)}
              >
                {getCrawlerFailureClusterWebsiteLabel(cluster)}
              </p>
              <p class="text-muted-foreground mt-1 truncate text-xs">
                {getCrawlerFailureClusterAttributionLabel(cluster)}
              </p>
            </div>
            <p class="text-muted-foreground text-sm">
              {getCrawlerFailureClusterWorkLabel(cluster)}
            </p>
            <div class="text-sm tabular-nums">
              <time datetime={cluster.latest_failed_at} class="text-foreground block">
                {getCrawlerFailureClusterLatestLabel(cluster)}
              </time>
              {#if clusterLatestRelative}
                <p class="text-muted-foreground mt-0.5 text-xs">
                  {clusterLatestRelative}
                </p>
              {/if}
            </div>
            <div class="flex items-center justify-start lg:justify-end">
              {#if resolved.inventoryItem}
                <Button
                  variant="ghost"
                  size="sm"
                  onclick={() =>
                    resolved.inventoryItem && onOpenWebsiteDetail(resolved.inventoryItem)}
                >
                  {m.crawler_inventory_row_action_view_detail()}
                  <ChevronRight data-icon="inline-end" aria-hidden="true" />
                </Button>
              {/if}
            </div>
          </article>
        {/each}
      </div>

      {#if failureClusters.visible.total > CRAWLER_FAILURE_CLUSTERS_PAGE_SIZE}
        <div class="mt-3 flex justify-end">
          <Pagination.Root
            count={failureClusters.visible.total}
            perPage={CRAWLER_FAILURE_CLUSTERS_PAGE_SIZE}
            page={failureClusters.page}
            onPageChange={(next) => failureClusters.onChangePage(next)}
            class="m-0 w-auto justify-end"
          >
            {#snippet children({ pages, currentPage })}
              <Pagination.Content>
                <Pagination.Item>
                  <Pagination.PrevButton disabled={failureClusters.busy} />
                </Pagination.Item>
                {#each pages as p (p.key)}
                  {#if p.type === "ellipsis"}
                    <Pagination.Item>
                      <Pagination.Ellipsis />
                    </Pagination.Item>
                  {:else}
                    <Pagination.Item>
                      <Pagination.Link
                        page={p}
                        isActive={currentPage === p.value}
                        disabled={failureClusters.busy}
                      >
                        {p.value}
                      </Pagination.Link>
                    </Pagination.Item>
                  {/if}
                {/each}
                <Pagination.Item>
                  <Pagination.NextButton disabled={failureClusters.busy} />
                </Pagination.Item>
              </Pagination.Content>
            {/snippet}
          </Pagination.Root>
        </div>
      {/if}
    {/if}
  </Card.Content>
</Card.Root>
