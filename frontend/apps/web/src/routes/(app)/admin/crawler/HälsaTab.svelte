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
  import * as Table from "$lib/components/ui/table/index.js";
  import { ShieldCheck, TriangleAlert } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import {
    getCrawlerCircuitBreakerResetCopy,
    type CrawlerCircuitBreakerResetCandidate
  } from "$lib/features/admin/crawlerCircuitBreakerReset";
  import {
    getCrawlerFailureInventoryFailureLabel,
    getCrawlerFailureInventoryLastCrawledLabel,
    getCrawlerFailureInventoryNextStepLabel,
    getCrawlerFailureInventoryStateLabel,
    getCrawlerFailureInventoryStateTooltip,
    getCrawlerFailureInventoryTotalLabel,
    getCrawlerFailureInventoryWebsiteLabel,
    type CrawlerTenantFailureInventoryResponse
  } from "$lib/features/admin/crawlerFailureInventory";
  import { groupCrawlerHealthRows } from "$lib/features/admin/crawlerHealthGrouping";
  import { crawlerFailureStateBadgeClass } from "$lib/features/admin/crawlerPresentation";
  import {
    CRAWLER_RECENT_FAILURES_PAGE_SIZE,
    getCrawlerRecentFailureOutcomeLabel,
    getCrawlerRecentFailureResultLabels,
    type CrawlerRecentFailuresResponse
  } from "$lib/features/admin/crawlerRecentFailures";
  import type { CrawlerTenantWebsiteInventoryItem } from "$lib/features/admin/crawlerTenantWebsiteInventory";
  import {
    CRAWLER_WATCHDOG_INTERVENTIONS_PAGE_SIZE,
    getCrawlerWatchdogInterventionOutcomeLabel,
    getCrawlerWatchdogInterventionResultLabels,
    type CrawlerWatchdogInterventionsResponse
  } from "$lib/features/admin/crawlerWatchdogInterventions";
  import EmptyState from "./EmptyState.svelte";
  import TerminalOutcomeFeedCard from "./TerminalOutcomeFeedCard.svelte";

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
    watchdog: PaginatedFeed<CrawlerWatchdogInterventionsResponse>;
    recentFailures: PaginatedFeed<CrawlerRecentFailuresResponse>;
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
    watchdog,
    recentFailures,
    mutationState,
    resolveRowLabel,
    onOpenWebsiteDetail,
    onOpenRetryDialog,
    onOpenIntervalDialog,
    onOpenCircuitResetDialog
  }: Props = $props();

  const groupedWatchdog = $derived(
    watchdog.visible
      ? groupCrawlerHealthRows(watchdog.visible.items, getCrawlerWatchdogInterventionOutcomeLabel)
      : []
  );

  const groupedRecentFailures = $derived(
    recentFailures.visible
      ? groupCrawlerHealthRows(recentFailures.visible.items, getCrawlerRecentFailureOutcomeLabel)
      : []
  );
</script>

<Card.Root class="mb-14" aria-labelledby="crawler-failure-inventory-title">
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
            {#each failureInventory.items as failureState (failureState.website_id)}
              {@const resetCopy = getCrawlerCircuitBreakerResetCopy(failureState)}
              {@const isResettingThis =
                mutationState.resettingCircuitWebsiteId === failureState.website_id}
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
                    class={crawlerFailureStateBadgeClass(failureState.state)}
                    title={getCrawlerFailureInventoryStateTooltip(failureState)}
                  >
                    {getCrawlerFailureInventoryStateLabel(failureState)}
                  </Badge>
                </Table.Cell>
                <Table.Cell class="tabular-nums">
                  {getCrawlerFailureInventoryFailureLabel(failureState)}
                </Table.Cell>
                <Table.Cell class="text-muted-foreground max-w-80 text-sm whitespace-normal">
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
                </Table.Cell>
              </Table.Row>
            {/each}
          </Table.Body>
        </Table.Root>
      </div>
    {/if}
  </Card.Content>
</Card.Root>

<TerminalOutcomeFeedCard
  titleId="crawler-watchdog-interventions-title"
  labels={{
    title: m.crawler_watchdog_interventions_title(),
    description: m.crawler_watchdog_interventions_description({ days: watchdog.windowDays }),
    count: watchdog.visible
      ? m.crawler_watchdog_interventions_count({
          shown: watchdog.visible.items.length,
          total: watchdog.visible.total
        })
      : "",
    loadError: m.crawler_watchdog_interventions_load_error(),
    emptyTitle: m.crawler_empty_watchdog_title(),
    emptyDescription: m.crawler_empty_watchdog_description(),
    tableCaption: m.crawler_watchdog_interventions_table_caption(),
    columnWebsite: m.crawler_watchdog_interventions_column_website(),
    columnOutcome: m.crawler_watchdog_interventions_column_outcome(),
    columnActivity: m.crawler_watchdog_interventions_column_activity(),
    columnFinished: m.crawler_watchdog_interventions_column_finished()
  }}
  feed={watchdog}
  groupedRows={groupedWatchdog}
  pageSize={CRAWLER_WATCHDOG_INTERVENTIONS_PAGE_SIZE}
  {resolveRowLabel}
  onOpenRowDetail={onOpenWebsiteDetail}
  outcomeLabelFn={getCrawlerWatchdogInterventionOutcomeLabel}
  resultLabelsFn={getCrawlerWatchdogInterventionResultLabels}
/>

<TerminalOutcomeFeedCard
  titleId="crawler-recent-failures-title"
  labels={{
    title: m.crawler_recent_failures_title(),
    description: m.crawler_recent_failures_description({ days: recentFailures.windowDays }),
    count: recentFailures.visible
      ? m.crawler_recent_failures_count({
          shown: recentFailures.visible.items.length,
          total: recentFailures.visible.total
        })
      : "",
    loadError: m.crawler_recent_failures_load_error(),
    emptyTitle: m.crawler_empty_recent_failures_title(),
    emptyDescription: m.crawler_empty_recent_failures_description(),
    tableCaption: m.crawler_recent_failures_table_caption(),
    columnWebsite: m.crawler_recent_failures_column_website(),
    columnOutcome: m.crawler_recent_failures_column_outcome(),
    columnActivity: m.crawler_recent_failures_column_activity(),
    columnFinished: m.crawler_recent_failures_column_finished()
  }}
  feed={recentFailures}
  groupedRows={groupedRecentFailures}
  pageSize={CRAWLER_RECENT_FAILURES_PAGE_SIZE}
  {resolveRowLabel}
  onOpenRowDetail={onOpenWebsiteDetail}
  outcomeLabelFn={getCrawlerRecentFailureOutcomeLabel}
  resultLabelsFn={getCrawlerRecentFailureResultLabels}
/>
