<script lang="ts">
  import { Table } from "@intric/ui";
  import { createRender } from "svelte-headless-table";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { derived } from "svelte/store";
  import type { IntegrationKnowledge } from "@intric/intric-js";
  import IntegrationNameCell from "./IntegrationNameCell.svelte";
  import IntegrationSyncStatusCell from "./IntegrationSyncStatusCell.svelte";
  import IntegrationActions from "./IntegrationActions.svelte";
  import SharePointWrapperActions from "./SharePointWrapperActions.svelte";
  import WrapperNameCell from "./WrapperNameCell.svelte";
  import { integrationData } from "$lib/features/integrations/IntegrationData";
  import { m } from "$lib/paraglide/messages";

  interface Props {
    onSelectIntegrationForSyncHistory?: (integration: IntegrationKnowledge) => void;
  }

  let { onSelectIntegrationForSyncHistory }: Props = $props();

  const {
    state: { currentSpace }
  } = getSpacesManager();

  const knowledge = derived(
    currentSpace,
    ($currentSpace) => $currentSpace.knowledge.integrationKnowledge.filter(k => k.space_id === $currentSpace.id)
  );

  // --- Wrapper grouping logic ---

  type SharePointItemTypeCounts = {
    files: number;
    folders: number;
    sites: number;
    unknown: number;
    total: number;
  };

  function getSharePointItemTypeCounts(items: IntegrationKnowledge[]): SharePointItemTypeCounts {
    let files = 0;
    let folders = 0;
    let sites = 0;
    let unknown = 0;

    for (const item of items) {
      const itemType = (item.selected_item_type ?? "").toLowerCase();
      if (itemType === "file") files += 1;
      else if (itemType === "folder") folders += 1;
      else if (itemType === "site_root" || itemType === "site") sites += 1;
      else unknown += 1;
    }

    return { files, folders, sites, unknown, total: items.length };
  }

  function getCountSubtitle(counts: SharePointItemTypeCounts): string {
    const parts: string[] = [];
    if (counts.files > 0) {
      parts.push(counts.files === 1
        ? m.sharepoint_wrapper_files_one({ count: counts.files })
        : m.sharepoint_wrapper_files_other({ count: counts.files }));
    }
    if (counts.folders > 0) {
      parts.push(counts.folders === 1
        ? m.sharepoint_wrapper_folders_one({ count: counts.folders })
        : m.sharepoint_wrapper_folders_other({ count: counts.folders }));
    }
    if (counts.sites > 0) {
      parts.push(counts.sites === 1
        ? m.sharepoint_wrapper_sites_one({ count: counts.sites })
        : m.sharepoint_wrapper_sites_other({ count: counts.sites }));
    }
    if (parts.length === 0) {
      parts.push(counts.total === 1
        ? m.wrapper_items_count_one({ count: counts.total })
        : m.wrapper_items_count_other({ count: counts.total }));
    }
    return parts.join(", ");
  }

  // --- Display items ---

  type WrapperDisplayItem = {
    kind: "wrapper";
    sortKey: string;
    wrapperId: string;
    wrapperName: string;
    itemCount: number;
    counts: SharePointItemTypeCounts;
    canEdit: boolean;
    canDelete: boolean;
    embeddingModelId: string;
  };

  type IntegrationDisplayItem = {
    kind: "item";
    sortKey: string;
    item: IntegrationKnowledge;
    embeddingModelId: string;
  };

  type DisplayItem = WrapperDisplayItem | IntegrationDisplayItem;

  const displayItems = derived([knowledge, currentSpace], ([$knowledge, $currentSpace]) => {
    // Group items by wrapper_id
    const wrapperMap = new Map<string, IntegrationKnowledge[]>();
    const noWrapper: IntegrationKnowledge[] = [];

    for (const item of $knowledge) {
      const wrapperId = item.wrapper_id ?? undefined;
      if (wrapperId && item.integration_type === "sharepoint") {
        const existing = wrapperMap.get(wrapperId) ?? [];
        existing.push(item);
        wrapperMap.set(wrapperId, existing);
      } else {
        noWrapper.push(item);
      }
    }

    const items: DisplayItem[] = [];

    // Process wrapper groups
    for (const [wrapperId, wrapperItems] of wrapperMap.entries()) {
      if (wrapperItems.length >= 2) {
        // Show as folder row
        const representative = wrapperItems[0];
        const wrapperName = (typeof representative.wrapper_name === "string" && representative.wrapper_name.trim().length > 0)
          ? representative.wrapper_name
          : representative.name;
        const counts = getSharePointItemTypeCounts(wrapperItems);
        const ownedItems = wrapperItems.filter(i => i.space_id === $currentSpace.id);
        const ownedInCurrentSpace = ownedItems.length > 0 && ownedItems.length === wrapperItems.length;
        const permissions = (ownedItems[0] ?? representative).permissions ?? [];

        items.push({
          kind: "wrapper",
          sortKey: wrapperName.toLowerCase(),
          wrapperId,
          wrapperName,
          itemCount: wrapperItems.length,
          counts,
          canEdit: ownedInCurrentSpace && permissions.includes("edit"),
          canDelete: ownedInCurrentSpace && permissions.includes("delete"),
          embeddingModelId: representative.embedding_model.id
        });
      } else {
        // Single item in wrapper - show as regular item
        for (const item of wrapperItems) {
          items.push({
            kind: "item",
            sortKey: item.name.toLowerCase(),
            item,
            embeddingModelId: item.embedding_model.id
          });
        }
      }
    }

    // Add non-wrapper items
    for (const item of noWrapper) {
      items.push({
        kind: "item",
        sortKey: item.name.toLowerCase(),
        item,
        embeddingModelId: item.embedding_model.id
      });
    }

    // Sort alphabetically
    items.sort((a, b) => a.sortKey.localeCompare(b.sortKey));

    return items;
  });

  // --- Embedding model groups ---

  const embeddingModels = derived(currentSpace, ($currentSpace) => {
    const modelsInSpace = $currentSpace.embedding_models.map((model) => model.id);
    const ownedKnowledge = $currentSpace.knowledge.integrationKnowledge.filter(k => k.space_id === $currentSpace.id);
    const modelsInIntegrationKnowledge = ownedKnowledge.map((item) => ({
      ...item.embedding_model,
      inSpace: modelsInSpace.includes(item.embedding_model.id)
    }));
    return modelsInIntegrationKnowledge.filter(
      (curr, idx, models) => idx === models.findIndex((other) => other.id === curr.id)
    );
  });

  const disabledModelInUse = derived(embeddingModels, ($embeddingModels) => {
    return [...$embeddingModels].findIndex((model) => model.inSpace === false) > -1;
  });

  const useEmbeddingModelGroups = derived(
    [embeddingModels, currentSpace, disabledModelInUse],
    ([$embeddingModels, $currentSpace, $disabledModelInUse]) =>
      $embeddingModels.length > 1 ||
      $currentSpace.embedding_models.length > 1 ||
      $disabledModelInUse
  );

  // --- Table setup ---

  const table = Table.createWithStore(displayItems);

  const viewModel = table.createViewModel([
    table.column({
      header: m.name(),
      accessor: (displayItem) => displayItem,
      cell: (displayItem) => {
        const di = displayItem.value;
        if (di.kind === "wrapper") {
          return createRender(WrapperNameCell, {
            name: di.wrapperName,
            link: `/spaces/${$currentSpace.routeId}/knowledge/integrations/wrapper/${di.wrapperId}`,
            itemCount: di.itemCount,
            subtitle: getCountSubtitle(di.counts)
          });
        }
        return createRender(IntegrationNameCell, {
          knowledge: di.item
        });
      }
    }),

    table.column({
      header: m.status(),
      accessor: (displayItem) => displayItem,
      cell: (displayItem) => {
        const di = displayItem.value;
        if (di.kind === "wrapper") {
          const countLabel = di.itemCount === 1
            ? m.wrapper_items_count_one({ count: di.itemCount })
            : m.wrapper_items_count_other({ count: di.itemCount });
          return createRender(Table.FormattedCell, { value: countLabel });
        }
        return createRender(IntegrationSyncStatusCell, {
          knowledge: di.item,
          onShowSyncHistory: onSelectIntegrationForSyncHistory
            ? () => onSelectIntegrationForSyncHistory(di.item)
            : undefined
        });
      }
    }),

    table.column({
      accessor: (displayItem) => displayItem,
      header: m.link(),
      cell: (displayItem) => {
        const di = displayItem.value;
        if (di.kind === "wrapper") {
          return createRender(Table.FormattedCell, { value: "" });
        }
        const labelKey = integrationData[di.item.integration_type].previewLinkLabel;
        const translatedLabel = m[labelKey as keyof typeof m]?.() ?? labelKey;
        return createRender(Table.ButtonCell, {
          link: di.item.url ?? "",
          label: translatedLabel,
          linkIsExternal: true
        });
      }
    }),

    table.columnActions({
      cell: (displayItem) => {
        const di = displayItem.value;
        if (di.kind === "wrapper") {
          return createRender(SharePointWrapperActions, {
            wrapperId: di.wrapperId,
            wrapperName: di.wrapperName,
            itemCount: di.itemCount,
            canEdit: di.canEdit,
            canDelete: di.canDelete
          });
        }
        return createRender(IntegrationActions, {
          knowledgeItem: di.item
        });
      }
    })
  ]);

  function createModelFilter(embeddingModelId: string) {
    return function (displayItem: DisplayItem) {
      return displayItem.embeddingModelId === embeddingModelId;
    };
  }
</script>

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
