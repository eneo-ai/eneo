<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).
    See the LICENSE file at the repository root for the full license text.
-->

<script lang="ts">
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { TriangleAlert } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import { formatCrawlerCount } from "$lib/features/admin/crawlerNumberFormat";
  import {
    formatCrawlerScheduledCount,
    formatCrawlerScheduledIndexedSize,
    getCrawlerScheduledAggregateTotalLabel,
    getCrawlerScheduledIntervalLabel,
    getCrawlerScheduledUnparseableLabel,
    type CrawlerScheduledAggregateResponse
  } from "$lib/features/admin/crawlerScheduledAggregate";
  import type { CrawlerTenantWebsiteInventoryItem } from "$lib/features/admin/crawlerTenantWebsiteInventory";
  import {
    getCrawlerWebsiteProcessingEmbeddingUsageLabel,
    getCrawlerWebsiteProcessingFailureLabel,
    getCrawlerWebsiteProcessingFetchedLabel,
    getCrawlerWebsiteProcessingLoadPressureLabel,
    getCrawlerWebsiteProcessingRetainedLabel,
    getCrawlerWebsiteProcessingTotalLabel,
    getCrawlerWebsiteProcessingWebsiteLabel,
    isCrawlerWebsiteProcessingLowRetention,
    isCrawlerWebsiteProcessingSourceSkipDrift,
    type CrawlerTenantWebsiteProcessingAggregateResponse
  } from "$lib/features/admin/crawlerWebsiteProcessing";

  type ResolvedRowLabel = {
    label: string;
    inventoryItem: CrawlerTenantWebsiteInventoryItem | null;
  };

  type Props = {
    scheduledAggregate: CrawlerScheduledAggregateResponse | null;
    scheduledAggregateLoadFailed: boolean;
    websiteProcessing: CrawlerTenantWebsiteProcessingAggregateResponse | null;
    websiteProcessingLoadFailed: boolean;
    websiteProcessingWindowDays: number;
    resolveRowLabel: (row: { website_id: string; website_name: string | null }) => ResolvedRowLabel;
    onOpenWebsiteDetail: (item: CrawlerTenantWebsiteInventoryItem) => void;
  };

  const {
    scheduledAggregate,
    scheduledAggregateLoadFailed,
    websiteProcessing,
    websiteProcessingLoadFailed,
    websiteProcessingWindowDays,
    resolveRowLabel,
    onOpenWebsiteDetail
  }: Props = $props();
</script>

<Card.Root class="mb-14" aria-labelledby="crawler-scheduled-title">
  <Card.Header>
    <div class="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
      <div class="flex min-w-0 flex-col gap-1">
        <h2 id="crawler-scheduled-title" class="text-base leading-snug font-semibold">
          {m.crawler_scheduled_title()}
        </h2>
        <Card.Description>{m.crawler_scheduled_description()}</Card.Description>
      </div>
      {#if scheduledAggregate}
        <Badge variant="outline" class="shrink-0 tabular-nums">
          {getCrawlerScheduledAggregateTotalLabel(scheduledAggregate)}
        </Badge>
      {/if}
    </div>
  </Card.Header>
  <Card.Content class="pt-0">
    {#if scheduledAggregateLoadFailed}
      <Alert.Root variant="destructive">
        <TriangleAlert aria-hidden="true" />
        <Alert.Description>{m.crawler_scheduled_load_error()}</Alert.Description>
      </Alert.Root>
    {:else if !scheduledAggregate || scheduledAggregate.total_websites === 0}
      <p class="text-muted-foreground text-sm">
        {m.crawler_scheduled_empty()}
      </p>
    {:else}
      {@const unparseableLabel = getCrawlerScheduledUnparseableLabel(scheduledAggregate)}
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
              {#each scheduledAggregate.buckets as bucket (bucket.update_interval)}
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
        <h2 id="crawler-website-processing-title" class="text-base leading-snug font-semibold">
          {m.crawler_website_processing_title()}
        </h2>
        <Card.Description>
          {m.crawler_website_processing_description({
            days: websiteProcessingWindowDays
          })}
        </Card.Description>
      </div>
      {#if websiteProcessing}
        <Badge variant="outline" class="shrink-0 tabular-nums">
          {getCrawlerWebsiteProcessingTotalLabel(websiteProcessing)}
        </Badge>
      {/if}
    </div>
  </Card.Header>
  <Card.Content class="pt-0">
    {#if websiteProcessingLoadFailed}
      <Alert.Root variant="destructive">
        <TriangleAlert aria-hidden="true" />
        <Alert.Description>{m.crawler_website_processing_load_error()}</Alert.Description>
      </Alert.Root>
    {:else if !websiteProcessing || websiteProcessing.items.length === 0}
      <p class="text-muted-foreground text-sm">
        {m.crawler_website_processing_empty({ days: websiteProcessingWindowDays })}
      </p>
    {:else}
      <div class="overflow-x-auto">
        <Table.Root class="min-w-[66rem]">
          <Table.Caption class="sr-only">
            {m.crawler_website_processing_table_caption()}
          </Table.Caption>
          <Table.Header>
            <Table.Row>
              <Table.Head>{m.crawler_website_processing_column_website()}</Table.Head>
              <Table.Head>{m.crawler_website_processing_column_load_pressure()}</Table.Head>
              <Table.Head>{m.crawler_website_processing_column_embedding_usage()}</Table.Head>
              <Table.Head>{m.crawler_website_processing_column_runs()}</Table.Head>
              <Table.Head>{m.crawler_website_processing_column_fetched()}</Table.Head>
              <Table.Head>{m.crawler_website_processing_column_retained()}</Table.Head>
              <Table.Head>{m.crawler_website_processing_column_failures()}</Table.Head>
            </Table.Row>
          </Table.Header>
          <Table.Body>
            {#each websiteProcessing.items as processingItem (processingItem.website_id)}
              {@const failureLabel = getCrawlerWebsiteProcessingFailureLabel(processingItem)}
              {@const processingResolved = resolveRowLabel(processingItem)}
              <Table.Row
                class={processingResolved.inventoryItem
                  ? "hover:bg-muted/40 focus-within:bg-muted/40 cursor-pointer"
                  : ""}
                onclick={() =>
                  processingResolved.inventoryItem &&
                  onOpenWebsiteDetail(processingResolved.inventoryItem)}
              >
                <Table.Cell class="max-w-64">
                  <span
                    class="block truncate font-medium"
                    title={processingResolved.inventoryItem
                      ? processingResolved.label
                      : getCrawlerWebsiteProcessingWebsiteLabel(processingItem)}
                  >
                    {processingResolved.inventoryItem
                      ? processingResolved.label
                      : getCrawlerWebsiteProcessingWebsiteLabel(processingItem)}
                  </span>
                </Table.Cell>
                <Table.Cell>
                  <Badge
                    variant="outline"
                    class="tabular-nums"
                    title={m.crawler_website_processing_load_pressure_hint()}
                  >
                    {getCrawlerWebsiteProcessingLoadPressureLabel(processingItem)}
                  </Badge>
                </Table.Cell>
                <Table.Cell>
                  <Badge
                    variant="outline"
                    class="tabular-nums"
                    title={m.crawler_website_processing_embedding_usage_hint()}
                  >
                    {getCrawlerWebsiteProcessingEmbeddingUsageLabel(processingItem)}
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
                    <Badge variant="outline" class="border-accent-default/35 text-accent-default">
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
                    <Badge variant="outline" class="border-caution/40 bg-caution/8 text-caution">
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
