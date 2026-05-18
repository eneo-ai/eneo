<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).
    See the LICENSE file at the repository root for the full license text.
-->

<script
  lang="ts"
  generics="TItem extends { website_id: string; website_name: string | null; crawl_run_id: string; finished_at: string }, TResponse extends { items: readonly TItem[]; total: number }"
>
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Pagination from "$lib/components/ui/pagination/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { ShieldCheck, TriangleAlert } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import type { CrawlerHealthGroup } from "$lib/features/admin/crawlerHealthGrouping";
  import {
    crawlerResultBadgeClass,
    formatCrawlerDateTime
  } from "$lib/features/admin/crawlerPresentation";
  import type { CrawlerTenantWebsiteInventoryItem } from "$lib/features/admin/crawlerTenantWebsiteInventory";
  import type { CrawlRunResultLabel } from "$lib/features/knowledge/crawlOutcomePresentation";
  import EmptyState from "./EmptyState.svelte";

  type ResolvedRowLabel = {
    label: string;
    inventoryItem: CrawlerTenantWebsiteInventoryItem | null;
  };

  type PaginatedFeed = {
    visible: TResponse | null;
    loadFailed: boolean;
    page: number;
    busy: boolean;
    onChangePage: (next: number) => void;
  };

  type Labels = {
    title: string;
    description: string;
    count: string;
    loadError: string;
    emptyTitle: string;
    emptyDescription: string;
    tableCaption: string;
    columnWebsite: string;
    columnOutcome: string;
    columnActivity: string;
    columnFinished: string;
  };

  type Props = {
    titleId: string;
    labels: Labels;
    feed: PaginatedFeed;
    groupedRows: readonly CrawlerHealthGroup<TItem>[];
    pageSize: number;
    resolveRowLabel: (row: { website_id: string; website_name: string | null }) => ResolvedRowLabel;
    onOpenRowDetail: (item: CrawlerTenantWebsiteInventoryItem) => void;
    outcomeLabelFn: (item: TItem) => string;
    resultLabelsFn: (item: TItem) => readonly CrawlRunResultLabel[];
  };

  const {
    titleId,
    labels,
    feed,
    groupedRows,
    pageSize,
    resolveRowLabel,
    onOpenRowDetail,
    outcomeLabelFn,
    resultLabelsFn
  }: Props = $props();
</script>

<Card.Root class="mb-14" aria-labelledby={titleId}>
  <Card.Header>
    <div class="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
      <div class="flex min-w-0 flex-col gap-1">
        <h2 id={titleId} class="text-base leading-snug font-semibold">
          {labels.title}
        </h2>
        <Card.Description>{labels.description}</Card.Description>
      </div>
      {#if feed.visible}
        <Badge variant="outline" class="shrink-0 tabular-nums">
          {labels.count}
        </Badge>
      {/if}
    </div>
  </Card.Header>
  <Card.Content class="pt-0" aria-busy={feed.busy}>
    {#if feed.loadFailed}
      <Alert.Root variant="destructive">
        <TriangleAlert aria-hidden="true" />
        <Alert.Description>{labels.loadError}</Alert.Description>
      </Alert.Root>
    {:else if !feed.visible || feed.visible.items.length === 0}
      <EmptyState title={labels.emptyTitle} description={labels.emptyDescription}>
        {#snippet icon()}
          <ShieldCheck class="size-5" />
        {/snippet}
      </EmptyState>
    {:else}
      <div class="overflow-x-auto">
        <Table.Root class="min-w-[56rem]">
          <Table.Caption class="sr-only">{labels.tableCaption}</Table.Caption>
          <Table.Header>
            <Table.Row>
              <Table.Head>{labels.columnWebsite}</Table.Head>
              <Table.Head>{labels.columnOutcome}</Table.Head>
              <Table.Head>{labels.columnActivity}</Table.Head>
              <Table.Head class="text-right">{labels.columnFinished}</Table.Head>
            </Table.Row>
          </Table.Header>
          <Table.Body>
            {#each groupedRows as group (group.representative.crawl_run_id)}
              {@const item = group.representative}
              {@const resolved = resolveRowLabel(item)}
              <Table.Row
                class={resolved.inventoryItem
                  ? "hover:bg-muted/40 focus-within:bg-muted/40 cursor-pointer"
                  : ""}
                onclick={() => resolved.inventoryItem && onOpenRowDetail(resolved.inventoryItem)}
              >
                <Table.Cell class="max-w-64">
                  <span class="block truncate font-medium" title={resolved.label}>
                    {resolved.label}
                  </span>
                </Table.Cell>
                <Table.Cell class="max-w-72 whitespace-normal">
                  <div class="flex flex-wrap items-center gap-2">
                    <span class="text-sm">{outcomeLabelFn(item)}</span>
                    {#if group.count > 1}
                      <Badge
                        variant="outline"
                        class="tabular-nums"
                        title={m.crawler_health_group_count_tooltip({
                          first: formatCrawlerDateTime(group.firstFinishedAt),
                          latest: formatCrawlerDateTime(group.latestFinishedAt)
                        })}
                      >
                        ×&nbsp;{group.count}
                      </Badge>
                    {/if}
                  </div>
                </Table.Cell>
                <Table.Cell class="whitespace-normal">
                  <div class="flex flex-wrap gap-1.5">
                    {#each resultLabelsFn(item) as label (label.label)}
                      <Badge
                        variant="outline"
                        class={crawlerResultBadgeClass(label.color)}
                        title={label.tooltip}
                      >
                        {label.label}
                      </Badge>
                    {/each}
                  </div>
                </Table.Cell>
                <Table.Cell class="text-muted-foreground text-right text-xs tabular-nums">
                  {formatCrawlerDateTime(group.latestFinishedAt)}
                </Table.Cell>
              </Table.Row>
            {/each}
          </Table.Body>
        </Table.Root>
      </div>
      {#if feed.visible.total > pageSize}
        <div class="mt-4 flex items-center justify-end">
          <Pagination.Root
            count={feed.visible.total}
            perPage={pageSize}
            page={feed.page}
            onPageChange={(next) => feed.onChangePage(next)}
            class="m-0 w-auto justify-end"
          >
            {#snippet children({ pages, currentPage })}
              <Pagination.Content>
                <Pagination.Item>
                  <Pagination.PrevButton disabled={feed.busy} />
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
                        disabled={feed.busy}
                      >
                        {p.value}
                      </Pagination.Link>
                    </Pagination.Item>
                  {/if}
                {/each}
                <Pagination.Item>
                  <Pagination.NextButton disabled={feed.busy} />
                </Pagination.Item>
              </Pagination.Content>
            {/snippet}
          </Pagination.Root>
        </div>
      {/if}
    {/if}
  </Card.Content>
</Card.Root>
