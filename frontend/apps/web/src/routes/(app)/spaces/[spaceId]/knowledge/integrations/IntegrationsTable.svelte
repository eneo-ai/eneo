<script lang="ts">
  import * as Table from "$lib/components/resource-table/index.js";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { tick, untrack } from "svelte";
  import { derived, writable } from "svelte/store";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import { Button } from "$lib/components/ui/button/index.js";
  import { formatRelativeTime } from "$lib/core/formatting/dateTime";
  import SourceStatusFilter from "$lib/features/integrations/components/SourceStatusFilter.svelte";
  import {
    countSourceFilters,
    groupIntegrationSources,
    isSyncActive,
    matchesSourceFilter,
    sourceContentsLabel,
    sourceHref,
    sourceKey,
    summarizeSource,
    type IntegrationSource,
    type SourceFilter,
    type SourceSummary
  } from "$lib/features/integrations/sources";
  import { SourceAnnouncer } from "$lib/features/integrations/syncAnnouncements";
  import type { IntegrationSyncProgress } from "$lib/features/integrations/syncProgress";
  import { useSyncProgress } from "$lib/features/integrations/useSyncProgress.svelte";
  import { m } from "$lib/paraglide/messages";
  import { embeddingModelGroupTitle } from "$lib/features/ai-models/modelLabels";
  import IntegrationActions from "./IntegrationActions.svelte";
  import SharePointWrapperActions from "./SharePointWrapperActions.svelte";
  import SourceNameCell from "./SourceNameCell.svelte";
  import SourceStatusCell from "./SourceStatusCell.svelte";

  interface Props {
    /** Off while another tab of the knowledge page is open: the list stays mounted there. */
    active?: boolean;
  }

  let { active = true }: Props = $props();

  const {
    state: { currentSpace }
  } = getSpacesManager();

  const tracker = useSyncProgress({ active: () => active });
  const progress = writable<Record<string, IntegrationSyncProgress>>({});
  const queued = writable<ReadonlySet<string>>(new Set());
  $effect(() => {
    progress.set(tracker.byId);
  });
  $effect(() => {
    queued.set(tracker.queued);
  });

  type SourceRow = { source: IntegrationSource; summary: SourceSummary };

  const rows = derived([currentSpace, progress, queued], ([$currentSpace, $progress, $queued]) =>
    groupIntegrationSources(
      $currentSpace.knowledge.integrationKnowledge.filter((k) => k.space_id === $currentSpace.id)
    ).map((source): SourceRow => ({
      source,
      summary: summarizeSource(source.items, $progress, $queued)
    }))
  );

  // Only a sync started from this list is spoken here, once each step; counts and
  // change notifications' background syncs belong to the source's own page.
  let announcement = $state("");
  let announcers: Record<string, SourceAnnouncer> = {};
  // Rows that never record an outcome bring no new summary; ask again when a wait ends.
  let recheck = $state(0);
  $effect(() => {
    const current = $rows;
    void recheck;
    let timer: ReturnType<typeof setTimeout> | undefined;
    untrack(() => {
      const now = Date.now();
      const next: Record<string, SourceAnnouncer> = {};
      const messages: string[] = [];
      for (const { source, summary } of current) {
        const announcer =
          announcers[source.id] ??
          new SourceAnnouncer({ speakProgress: false, onlyStartedHere: true });
        next[source.id] = announcer;
        const text = announcer.next(source.name, summary, now);
        if (text) messages.push(text);
      }
      announcers = next;
      if (messages.length > 0) announcement = messages.join(". ");
      const waits = Object.values(next)
        .map((announcer) => announcer.awaitingUntil)
        .filter((until): until is number => until !== null);
      if (waits.length > 0) {
        timer = setTimeout(() => recheck++, Math.max(0, Math.min(...waits) - Date.now()));
      }
    });
    return () => clearTimeout(timer);
  });

  const statusFilter = writable<SourceFilter>("all");
  const visibleRows = derived([rows, statusFilter], ([$rows, $statusFilter]) =>
    $rows.filter((row) => matchesSourceFilter(row.summary, $statusFilter))
  );
  let filterCounts = $derived(countSourceFilters($rows.map((row) => row.summary)));
  // Once a filter has been chosen the bar stays, so the pressed button never vanishes under focus.
  let filterUsed = $state(false);
  $effect(() => {
    if ($statusFilter !== "all") filterUsed = true;
  });
  let showFilterBar = $derived($rows.length > 1 || filterUsed);
  let noMatch = $derived($rows.length > 0 && $visibleRows.length === 0);
  let filterBar = $state<HTMLElement>();

  async function showAllSources() {
    $statusFilter = "all";
    await tick();
    filterBar?.querySelector<HTMLElement>('button[aria-pressed="true"]')?.focus();
  }

  // The badges already mark failing sources; only a refused SharePoint sign-in, which
  // stops every source and only an admin can fix, gets a banner of its own.
  let signInStopped = $derived(
    $rows.filter((row) => row.summary.failedItems.length > 0 && row.summary.credentialsFailed)
  );

  // --- Embedding model groups ---

  const embeddingModels = derived(currentSpace, ($currentSpace) => {
    const modelsInSpace = $currentSpace.embedding_models.map((model) => model.id);
    const ownedKnowledge = $currentSpace.knowledge.integrationKnowledge.filter(
      (k) => k.space_id === $currentSpace.id
    );
    const modelsInIntegrationKnowledge = ownedKnowledge.map((item) => ({
      ...item.embedding_model,
      inSpace: modelsInSpace.includes(item.embedding_model.id)
    }));
    return modelsInIntegrationKnowledge.filter(
      (curr, idx, models) => idx === models.findIndex((other) => other.id === curr.id)
    );
  });

  // --- Table setup ---

  function permissionsOf(source: IntegrationSource) {
    const owned = source.items.filter((item) => item.space_id === $currentSpace.id);
    const permissions = owned.length === source.items.length ? (owned[0]?.permissions ?? []) : [];
    return { canEdit: permissions.includes("edit"), canDelete: permissions.includes("delete") };
  }

  function updatedLabel(summary: SourceSummary): string {
    if (summary.progress) return m.integration_source_updating_now();
    if (summary.lastSyncedAt) return formatRelativeTime(summary.lastSyncedAt);
    if (summary.lastSyncAttemptedAt) {
      return m.integration_source_last_attempt_at({
        time: formatRelativeTime(summary.lastSyncAttemptedAt)
      });
    }
    return "–";
  }

  const STATE_ORDER: SourceSummary["state"][] = [
    "attention",
    "syncing",
    "queued",
    "never",
    "empty",
    "ok"
  ];

  function timeOf(value: string | null): number {
    return value ? new Date(value).getTime() : 0;
  }

  // Keyed by source: filtering must not slide another source under a row's open dialog.
  const table = Table.createWithStore(visibleRows, undefined, {
    getRowId: (row) => sourceKey(row.source)
  });

  const viewModel = table.createViewModel([
    table.column({
      header: m.integration_source_column_source(),
      accessor: (row) => row,
      cell: ({ value: row }) =>
        Table.renderComponent(SourceNameCell, {
          name: row.source.name,
          integrationType: row.source.integrationType,
          href: sourceHref($currentSpace.routeId, row.source),
          subtitle: sourceContentsLabel(row.source.items),
          originalName: row.source.kind === "item" ? row.source.items[0].original_name : null
        }),
      plugins: {
        // A source is found by its own name or by any of its folders' names.
        tableFilter: {
          getFilterValue: (row) =>
            [row.source.name, ...row.source.items.map((item) => item.name)].join(" ")
        },
        sort: { getSortValue: (row) => row.source.name.toLowerCase() }
      }
    }),
    table.column({
      header: m.integration_source_column_contents(),
      accessor: (row) => row,
      cell: ({ value: row }) =>
        Table.renderComponent(Table.FormattedCell, {
          value:
            row.summary.documentCount === 1
              ? m.integration_documents_one({ count: row.summary.documentCount })
              : m.integration_documents_other({ count: row.summary.documentCount })
        }),
      plugins: {
        tableFilter: { exclude: true },
        sort: { getSortValue: (row) => row.summary.documentCount }
      }
    }),
    table.column({
      header: m.status(),
      accessor: (row) => row,
      cell: ({ value: row }) =>
        Table.renderComponent(SourceStatusCell, {
          summary: row.summary,
          sourceName: row.source.name
        }),
      plugins: {
        tableFilter: { exclude: true },
        sort: { getSortValue: (row) => STATE_ORDER.indexOf(row.summary.state) }
      }
    }),
    table.column({
      header: m.integration_source_column_updated(),
      accessor: (row) => row,
      cell: ({ value: row }) =>
        Table.renderComponent(Table.FormattedCell, {
          value: updatedLabel(row.summary),
          class: "text-secondary"
        }),
      plugins: {
        tableFilter: { exclude: true },
        sort: {
          getSortValue: (row) => timeOf(row.summary.lastSyncedAt ?? row.summary.lastSyncAttemptedAt)
        }
      }
    }),
    table.columnActions({
      cell: ({ value: row }) => {
        const source = row.source;
        if (source.kind === "wrapper") {
          const { canEdit, canDelete } = permissionsOf(source);
          return Table.renderComponent(SharePointWrapperActions, {
            wrapperId: source.id,
            wrapperName: source.name,
            itemCount: source.items.length,
            items: source.items,
            canEdit,
            canDelete,
            syncActive: isSyncActive(row.summary)
          });
        }
        return Table.renderComponent(IntegrationActions, {
          knowledgeItem: source.items[0],
          syncActive: isSyncActive(row.summary)
        });
      }
    })
  ]);

  function createModelFilter(embeddingModelId: string) {
    return (row: SourceRow) => row.source.embeddingModelId === embeddingModelId;
  }
</script>

<p class="sr-only" role="status" aria-live="polite">{announcement}</p>

{#if signInStopped.length > 0}
  {@const first = signInStopped[0]}
  <div
    class="border-negative-default bg-negative-dimmer text-negative-stronger mt-3 mr-3 flex flex-wrap items-start gap-3 rounded-lg border px-4 py-3 text-sm"
    role="status"
  >
    <TriangleAlert class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
    <div class="flex min-w-0 flex-1 flex-col gap-0.5">
      <p class="font-medium">
        {signInStopped.length === 1
          ? m.integration_sources_attention_one()
          : m.integration_sources_attention_other({ count: signInStopped.length })}
      </p>
      <p>
        {m.integration_sources_attention_sign_in()}
      </p>
    </div>
    {#if signInStopped.length === 1}
      <!-- eslint-disable svelte/no-navigation-without-resolve -- dynamic space route -->
      <a
        href={sourceHref($currentSpace.routeId, first.source, { tab: "problems" })}
        class="focus-visible:ring-stronger shrink-0 rounded font-medium underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:outline-none"
      >
        {m.integration_sources_attention_open_one()}
      </a>
      <!-- eslint-enable svelte/no-navigation-without-resolve -->
    {:else if $statusFilter !== "attention"}
      <button
        type="button"
        onclick={() => ($statusFilter = "attention")}
        class="focus-visible:ring-stronger shrink-0 rounded font-medium underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:outline-none"
      >
        {m.integration_sources_attention_show_them()}
      </button>
    {/if}
  </div>
{/if}

{#if showFilterBar && $rows.length > 0}
  <div class="pt-3 pr-3" bind:this={filterBar}>
    <SourceStatusFilter counts={filterCounts} bind:value={$statusFilter} />
    <!-- Mounted with the bar, so the message is announced when it appears. -->
    <p class="sr-only" role="status">{noMatch ? m.integration_filter_no_match() : ""}</p>
  </div>
{/if}

{#if noMatch}
  <div class="flex flex-col items-start gap-3 py-8 pr-3 text-sm">
    <p class="text-secondary">{m.integration_filter_no_match()}</p>
    <Button variant="outline" size="sm" onclick={showAllSources}>
      {m.integration_filter_show_all()}
    </Button>
  </div>
{:else}
  <Table.Root {viewModel} resourceName="integration">
    {#each $embeddingModels as embeddingModel (embeddingModel.id)}
      <Table.Group
        title={embeddingModelGroupTitle(embeddingModel, embeddingModel.inSpace)}
        filterFn={createModelFilter(embeddingModel.id)}
      ></Table.Group>
    {/each}
  </Table.Root>
{/if}
