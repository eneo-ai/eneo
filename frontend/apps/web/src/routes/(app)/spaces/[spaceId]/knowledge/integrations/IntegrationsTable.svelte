<script lang="ts">
  import * as Table from "$lib/components/resource-table/index.js";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { derived, writable } from "svelte/store";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import { formatRelativeTime } from "$lib/core/formatting/dateTime";
  import {
    groupIntegrationSources,
    sourceContentsLabel,
    sourceHref,
    summarizeSource,
    type IntegrationSource,
    type SourceSummary
  } from "$lib/features/integrations/sources";
  import type { IntegrationSyncProgress } from "$lib/features/integrations/syncProgress";
  import { useSyncProgress } from "$lib/features/integrations/useSyncProgress.svelte";
  import { m } from "$lib/paraglide/messages";
  import IntegrationActions from "./IntegrationActions.svelte";
  import SharePointWrapperActions from "./SharePointWrapperActions.svelte";
  import SourceNameCell from "./SourceNameCell.svelte";
  import SourceStatusCell from "./SourceStatusCell.svelte";

  const {
    state: { currentSpace }
  } = getSpacesManager();

  const tracker = useSyncProgress();
  const progress = writable<Record<string, IntegrationSyncProgress>>({});
  $effect(() => {
    progress.set(tracker.byId);
  });

  type SourceRow = { source: IntegrationSource; summary: SourceSummary };

  const rows = derived([currentSpace, progress], ([$currentSpace, $progress]) =>
    groupIntegrationSources(
      $currentSpace.knowledge.integrationKnowledge.filter((k) => k.space_id === $currentSpace.id)
    ).map((source): SourceRow => ({ source, summary: summarizeSource(source.items, $progress) }))
  );

  // A source that syncs right now can still have folders whose latest sync failed.
  let needsAttention = $derived($rows.filter((row) => row.summary.failedItems.length > 0));
  let attentionIsSignIn = $derived(
    needsAttention.length > 0 && needsAttention.every((row) => row.summary.credentialsFailed)
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

  const useEmbeddingModelGroups = derived(
    [embeddingModels, currentSpace],
    ([$embeddingModels, $currentSpace]) =>
      $embeddingModels.length > 1 ||
      $currentSpace.embedding_models.length > 1 ||
      $embeddingModels.some((model) => !model.inSpace)
  );

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

  const STATE_ORDER: SourceSummary["state"][] = ["attention", "syncing", "never", "empty", "ok"];

  function timeOf(value: string | null): number {
    return value ? new Date(value).getTime() : 0;
  }

  const table = Table.createWithStore(rows);

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
          sourceName: row.source.name,
          problemsHref: sourceHref($currentSpace.routeId, row.source, { tab: "problems" })
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
            canDelete
          });
        }
        return Table.renderComponent(IntegrationActions, { knowledgeItem: source.items[0] });
      }
    })
  ]);

  function createModelFilter(embeddingModelId: string) {
    return (row: SourceRow) => row.source.embeddingModelId === embeddingModelId;
  }
</script>

{#if needsAttention.length > 0}
  {@const first = needsAttention[0]}
  <div
    class="border-negative-default bg-negative-dimmer text-negative-stronger mt-3 mr-3 flex flex-wrap items-start gap-3 rounded-lg border px-4 py-3 text-sm"
    role="status"
  >
    <TriangleAlert class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
    <div class="flex min-w-0 flex-1 flex-col gap-0.5">
      <p class="font-medium">
        {needsAttention.length === 1
          ? m.integration_sources_attention_one()
          : m.integration_sources_attention_other({ count: needsAttention.length })}
      </p>
      <p>
        {attentionIsSignIn
          ? m.integration_sources_attention_sign_in()
          : m.integration_sources_attention_generic()}
      </p>
    </div>
    <!-- eslint-disable svelte/no-navigation-without-resolve -- dynamic space route -->
    <a
      href={sourceHref($currentSpace.routeId, first.source, { tab: "problems" })}
      class="focus-visible:ring-stronger shrink-0 rounded font-medium underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:outline-none"
    >
      {needsAttention.length === 1
        ? m.integration_sources_attention_open_one()
        : m.integration_sources_attention_open_first({ name: first.source.name })}
    </a>
    <!-- eslint-enable svelte/no-navigation-without-resolve -->
  </div>
{/if}

<Table.Root {viewModel} resourceName="integration">
  {#if $useEmbeddingModelGroups}
    {#each $embeddingModels as embeddingModel (embeddingModel.id)}
      <Table.Group
        title={embeddingModel.inSpace
          ? embeddingModel.name
          : embeddingModel.name + ` (${m.disabled()})`}
        filterFn={createModelFilter(embeddingModel.id)}
      ></Table.Group>
    {/each}
  {:else}
    <Table.Group></Table.Group>
  {/if}
</Table.Root>
