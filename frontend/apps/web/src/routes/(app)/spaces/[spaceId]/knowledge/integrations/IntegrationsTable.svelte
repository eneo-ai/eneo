<script lang="ts">
  import { Table } from "@intric/ui";
  import { createRender } from "svelte-headless-table";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { derived, get } from "svelte/store";
  import type { IntegrationKnowledge } from "@intric/intric-js";
  import IntegrationNameCell from "./IntegrationNameCell.svelte";
  import IntegrationSyncStatusCell from "./IntegrationSyncStatusCell.svelte";
  import IntegrationActions from "./IntegrationActions.svelte";
  import SharePointWrapperActions from "./SharePointWrapperActions.svelte";
  import { integrationData } from "$lib/features/integrations/IntegrationData";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";

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

  const embeddingModels = derived(currentSpace, ($currentSpace) => {
    const modelsInSpace = $currentSpace.embedding_models.map((model) => model.id);
    const ownedKnowledge = $currentSpace.knowledge.integrationKnowledge.filter(k => k.space_id === $currentSpace.id);
    const modelsInIntegrationKnowledge = ownedKnowledge.map(
      (collection) => {
        return {
          ...collection.embedding_model,
          inSpace: modelsInSpace.includes(collection.embedding_model.id)
        };
      }
    );
    // Need to remove duplicates from array
    const models = modelsInIntegrationKnowledge.filter(
      // will be true if this is the first time the model is mentioned
      (curr, idx, models) => idx === models.findIndex((other) => other.id === curr.id)
    );
    return models;
  });
  const disabledModelInUse = derived(embeddingModels, ($embeddingModels) => {
    return [...$embeddingModels].findIndex((model) => model.inSpace === false) > -1;
  });

  type MessageFn = (args?: Record<string, unknown>) => string;

  function resolveMessage(
    key: string,
    fallback: string,
    args?: Record<string, unknown>
  ): string {
    const maybeFn = (m as unknown as Record<string, MessageFn | undefined>)[key];
    if (typeof maybeFn === "function") {
      return maybeFn(args);
    }
    return fallback;
  }

  function getWrapperId(item: IntegrationKnowledge): string | undefined {
    return item.wrapper_id ?? undefined;
  }

  function getWrapperName(item: IntegrationKnowledge): string | undefined {
    const wrapperName = item.wrapper_name;
    if (typeof wrapperName === "string" && wrapperName.trim().length > 0) {
      return wrapperName;
    }
    return undefined;
  }

  function getWrapperGroupTitle(item: IntegrationKnowledge): string {
    return getWrapperName(item) ?? item.name;
  }

  function getWrapperCounts(items: IntegrationKnowledge[]): Map<string, number> {
    const counts = new Map<string, number>();
    for (const item of items) {
      if (item.integration_type !== "sharepoint") continue;
      const wrapperId = getWrapperId(item);
      if (!wrapperId) continue;
      counts.set(wrapperId, (counts.get(wrapperId) ?? 0) + 1);
    }
    return counts;
  }

  type SharePointItemTypeCounts = {
    files: number;
    folders: number;
    sites: number;
    unknown: number;
    total: number;
  };

  type SharePointCountType = "files" | "folders" | "sites" | "items";

  function getSharePointCountText(type: SharePointCountType, count: number): string {
    const form = count === 1 ? "one" : "other";
    if (type === "files") {
      return resolveMessage(
        `sharepoint_wrapper_files_${form}`,
        `${count} ${count === 1 ? "file" : "files"}`,
        { count }
      );
    }
    if (type === "folders") {
      return resolveMessage(
        `sharepoint_wrapper_folders_${form}`,
        `${count} ${count === 1 ? "folder" : "folders"}`,
        { count }
      );
    }
    if (type === "sites") {
      return resolveMessage(
        `sharepoint_wrapper_sites_${form}`,
        `${count} ${count === 1 ? "site" : "sites"}`,
        { count }
      );
    }
    return resolveMessage(
      `sharepoint_wrapper_items_${form}`,
      `${count} ${count === 1 ? "item" : "items"}`,
      { count }
    );
  }

  function getSharePointItemTypeCounts(items: IntegrationKnowledge[]): SharePointItemTypeCounts {
    let files = 0;
    let folders = 0;
    let sites = 0;
    let unknown = 0;

    for (const item of items) {
      const itemType = (item.selected_item_type ?? "").toLowerCase();
      if (itemType === "file") {
        files += 1;
      } else if (itemType === "folder") {
        folders += 1;
      } else if (itemType === "site_root" || itemType === "site") {
        sites += 1;
      } else {
        unknown += 1;
      }
    }

    return { files, folders, sites, unknown, total: items.length };
  }

  function shouldUseWrapperGroup(
    item: IntegrationKnowledge,
    wrapperCounts: Map<string, number>
  ): boolean {
    const wrapperId = getWrapperId(item);
    if (!wrapperId) return false;
    return (wrapperCounts.get(wrapperId) ?? 0) > 1;
  }

  function getGroupCountBadges(counts: SharePointItemTypeCounts): string[] {
    const badges: string[] = [];

    if (counts.files > 0) {
      badges.push(getSharePointCountText("files", counts.files));
    }
    if (counts.folders > 0) {
      badges.push(getSharePointCountText("folders", counts.folders));
    }
    if (counts.sites > 0) {
      badges.push(getSharePointCountText("sites", counts.sites));
    }
    if (counts.unknown > 0 || badges.length === 0) {
      const fallbackCount = counts.unknown > 0 ? counts.unknown : counts.total;
      badges.push(getSharePointCountText("items", fallbackCount));
    }

    return badges;
  }

  function getOtherIntegrationsLabel(): string {
    return resolveMessage("other_integrations", "Other integrations");
  }

  function getUngroupedItemsLabel(): string {
    const localeFallback = getLocale() === "sv" ? "Enskilda objekt" : "Individual items";
    return resolveMessage("sharepoint_ungrouped_items", localeFallback);
  }

  type SharePointWrapperGroup = {
    key: string;
    title: string;
    itemCount: number;
    counts: SharePointItemTypeCounts;
    itemIds: string[];
    wrapperId?: string;
    wrapperName?: string;
    isWrapperGroup: boolean;
    canEditWrapper: boolean;
    canDeleteWrapper: boolean;
  };

  const sharepointWrapperGroups = derived([knowledge, currentSpace], ([$knowledge, $currentSpace]) => {
    const wrapperCounts = getWrapperCounts($knowledge);
    const groups = new Map<
      string,
      {
        key: string;
        title: string;
        items: IntegrationKnowledge[];
        isWrapperGroup: boolean;
        wrapperId?: string;
        wrapperName?: string;
      }
    >();

    for (const item of $knowledge) {
      if (item.integration_type !== "sharepoint") continue;
      const wrapperId = getWrapperId(item);
      const useWrapperGroup = shouldUseWrapperGroup(item, wrapperCounts);
      if (!useWrapperGroup || !wrapperId) continue;
      const key = `wrapper:${wrapperId}`;

      const existing = groups.get(key);
      if (existing) {
        existing.items.push(item);
        continue;
      }

      groups.set(key, {
        key,
        title: getWrapperGroupTitle(item),
        items: [item],
        isWrapperGroup: true,
        wrapperId,
        wrapperName: getWrapperName(item)
      });
    }

    const mapped: SharePointWrapperGroup[] = [...groups.values()].map((group) => {
      const ownedItems = group.items.filter((item) => item.space_id === $currentSpace.id);
      const ownedInCurrentSpace =
        ownedItems.length > 0 && ownedItems.length === group.items.length;
      const representative = ownedItems[0] ?? group.items[0];
      const permissions = representative.permissions ?? [];
      const counts = getSharePointItemTypeCounts(group.items);

      return {
        key: group.key,
        title: group.title,
        itemCount: group.items.length,
        counts,
        itemIds: group.items.map((item) => item.id),
        wrapperId: group.wrapperId,
        wrapperName: group.wrapperName,
        isWrapperGroup: group.isWrapperGroup,
        canEditWrapper:
          group.isWrapperGroup && ownedInCurrentSpace && permissions.includes("edit"),
        canDeleteWrapper:
          group.isWrapperGroup && ownedInCurrentSpace && permissions.includes("delete")
      };
    });

    return mapped.sort((a, b) => a.title.localeCompare(b.title));
  });

  const useSharepointWrapperGroups = derived(
    sharepointWrapperGroups,
    ($sharepointWrapperGroups) => $sharepointWrapperGroups.length > 0
  );

  const sharepointGroupedItemIds = derived(
    sharepointWrapperGroups,
    ($sharepointWrapperGroups) => $sharepointWrapperGroups.flatMap((group) => group.itemIds)
  );

  const sharepointWrapperMembership = derived(
    sharepointWrapperGroups,
    ($sharepointWrapperGroups) => {
      const map = new Map<string, string>();
      for (const group of $sharepointWrapperGroups) {
        const wrapperName = group.wrapperName ?? group.title;
        for (const itemId of group.itemIds) {
          map.set(itemId, wrapperName);
        }
      }
      return map;
    }
  );

  const hasUngroupedSharepointKnowledge = derived(
    [knowledge, sharepointGroupedItemIds],
    ([$knowledge, $sharepointGroupedItemIds]) => {
      const groupedIds = new Set($sharepointGroupedItemIds);
      return $knowledge.some(
        (item) => item.integration_type === "sharepoint" && !groupedIds.has(item.id)
      );
    }
  );

  const hasNonSharepointKnowledge = derived(
    knowledge,
    ($knowledge) => $knowledge.some((item) => item.integration_type !== "sharepoint")
  );

  const useEmbeddingModelGroups = derived(
    [embeddingModels, currentSpace, disabledModelInUse],
    ([$embeddingModels, $currentSpace, $disabledModelInUse]) =>
      $embeddingModels.length > 1 ||
      $currentSpace.embedding_models.length > 1 ||
      $disabledModelInUse
  );

  let embeddingGroupOpenState: Record<string, boolean> = {};

  function isEmbeddingGroupOpen(embeddingModelId: string): boolean {
    return embeddingGroupOpenState[embeddingModelId] !== false;
  }

  function setEmbeddingGroupOpen(embeddingModelId: string, open: boolean) {
    embeddingGroupOpenState = {
      ...embeddingGroupOpenState,
      [embeddingModelId]: open
    };
  }

  type EmbeddingSection = {
    embeddingModel: {
      id: string;
      name: string;
      inSpace: boolean;
    };
    wrapperGroups: SharePointWrapperGroup[];
    groupedSharepointIds: string[];
    hasUngroupedSharepoint: boolean;
    hasNonSharepoint: boolean;
  };

  const embeddingSections = derived(
    [embeddingModels, knowledge, sharepointWrapperGroups],
    ([$embeddingModels, $knowledge, $sharepointWrapperGroups]): EmbeddingSection[] => {
      const itemsById = new Map($knowledge.map((item) => [item.id, item]));
      const wrapperGroupsByEmbedding = new Map<string, SharePointWrapperGroup[]>();
      const groupedSharepointIdsByEmbedding = new Map<string, Set<string>>();

      for (const group of $sharepointWrapperGroups) {
        const itemsByEmbedding = new Map<string, IntegrationKnowledge[]>();
        for (const itemId of group.itemIds) {
          const item = itemsById.get(itemId);
          if (!item) continue;
          const embeddingId = item.embedding_model.id;
          const current = itemsByEmbedding.get(embeddingId) ?? [];
          current.push(item);
          itemsByEmbedding.set(embeddingId, current);
        }

        for (const [embeddingId, items] of itemsByEmbedding.entries()) {
          if (items.length === 0) continue;
          const permissions = items[0].permissions ?? [];
          const splitGroup: SharePointWrapperGroup = {
            key: `${group.key}:${embeddingId}`,
            title: group.title,
            itemCount: items.length,
            counts: getSharePointItemTypeCounts(items),
            itemIds: items.map((item) => item.id),
            wrapperId: group.wrapperId,
            wrapperName: group.wrapperName,
            isWrapperGroup: group.isWrapperGroup,
            canEditWrapper: group.isWrapperGroup && permissions.includes("edit"),
            canDeleteWrapper: group.isWrapperGroup && permissions.includes("delete")
          };

          const existingGroups = wrapperGroupsByEmbedding.get(embeddingId) ?? [];
          existingGroups.push(splitGroup);
          wrapperGroupsByEmbedding.set(embeddingId, existingGroups);

          const groupedIds = groupedSharepointIdsByEmbedding.get(embeddingId) ?? new Set<string>();
          for (const item of items) {
            groupedIds.add(item.id);
          }
          groupedSharepointIdsByEmbedding.set(embeddingId, groupedIds);
        }
      }

      return $embeddingModels.map((embeddingModel) => {
        const wrapperGroups = [...(wrapperGroupsByEmbedding.get(embeddingModel.id) ?? [])].sort(
          (a, b) => a.title.localeCompare(b.title)
        );
        const groupedSharepointIds = [
          ...(groupedSharepointIdsByEmbedding.get(embeddingModel.id) ?? new Set<string>())
        ];
        const groupedSharepointIdSet = new Set(groupedSharepointIds);

        const hasUngroupedSharepoint = $knowledge.some(
          (item) =>
            item.embedding_model.id === embeddingModel.id &&
            item.integration_type === "sharepoint" &&
            !groupedSharepointIdSet.has(item.id)
        );

        const hasNonSharepoint = $knowledge.some(
          (item) =>
            item.embedding_model.id === embeddingModel.id &&
            item.integration_type !== "sharepoint"
        );

        return {
          embeddingModel,
          wrapperGroups,
          groupedSharepointIds,
          hasUngroupedSharepoint,
          hasNonSharepoint
        };
      });
    }
  );

  const table = Table.createWithStore(knowledge);

  const viewModel = table.createViewModel([
    table.column({
      header: m.name(),
      accessor: (item) => item,
      cell: (item) => {
        const wrapperName = get(sharepointWrapperMembership).get(item.value.id);
        return createRender(IntegrationNameCell, {
          knowledge: item.value,
          wrapperName
        });
      }
    }),

    table.column({
      header: m.status(),
      accessor: (item) => item,
      cell: (item) => {
        return createRender(IntegrationSyncStatusCell, {
          knowledge: item.value,
          onShowSyncHistory: () => {
            if (onSelectIntegrationForSyncHistory) {
              onSelectIntegrationForSyncHistory(item.value);
            }
          }
        });
      }
    }),

    table.column({
      accessor: (item) => item,
      header: m.link(),
      cell: (item) => {
        const labelKey = integrationData[item.value.integration_type].previewLinkLabel;
        // Get the translated label from the message system
        const translatedLabel = m[labelKey as keyof typeof m]?.() ?? labelKey;
        return createRender(Table.ButtonCell, {
          link: item.value.url ?? "",
          label: translatedLabel,
          linkIsExternal: true
        });
      }
    }),

    table.columnActions({
      cell: (item) => {
        return createRender(IntegrationActions, {
          knowledgeItem: item.value
        });
      }
    })
  ]);

  function neverMatchFilter(): boolean {
    return false;
  }

  function createSharePointWrapperFilter(itemIds: string[], embeddingModelId?: string) {
    const idSet = new Set(itemIds);
    return function (item: IntegrationKnowledge) {
      return (
        item.integration_type === "sharepoint" &&
        idSet.has(item.id) &&
        (!embeddingModelId || item.embedding_model.id === embeddingModelId)
      );
    };
  }

  function createUngroupedSharepointFilter(
    groupedItemIds: string[],
    embeddingModelId?: string
  ) {
    const idSet = new Set(groupedItemIds);
    return function (item: IntegrationKnowledge) {
      return (
        item.integration_type === "sharepoint" &&
        !idSet.has(item.id) &&
        (!embeddingModelId || item.embedding_model.id === embeddingModelId)
      );
    };
  }

  function createNonSharepointFilter(embeddingModelId?: string) {
    return function (item: IntegrationKnowledge) {
      return (
        item.integration_type !== "sharepoint" &&
        (!embeddingModelId || item.embedding_model.id === embeddingModelId)
      );
    };
  }
</script>

<Table.Root {viewModel} resourceName="integration">
  {#if $useEmbeddingModelGroups}
    {#each $embeddingSections as section (section.embeddingModel.id)}
      <Table.Group
        title={section.embeddingModel.inSpace
          ? section.embeddingModel.name
          : section.embeddingModel.name + ` (${m.disabled()})`}
        filterFn={neverMatchFilter}
        open={isEmbeddingGroupOpen(section.embeddingModel.id)}
        on:openChange={(event) =>
          setEmbeddingGroupOpen(
            section.embeddingModel.id,
            event.detail.open
          )}
        showEmptyRow={false}
      ></Table.Group>
      {#if isEmbeddingGroupOpen(section.embeddingModel.id)}
        {#each section.wrapperGroups as sourceGroup (sourceGroup.key)}
          <Table.Group
            title={sourceGroup.title}
            filterFn={createSharePointWrapperFilter(sourceGroup.itemIds, section.embeddingModel.id)}
          >
            <svelte:fragment slot="title-prefix">
              <span
                aria-hidden="true"
                class="border-label-default inline-block h-3 w-3 shrink-0 rounded-bl border-b border-l"
              ></span>
            </svelte:fragment>
            <svelte:fragment slot="title-suffix">
              <div class="flex items-center gap-2">
                <span class="label-neutral border-label-default bg-label-dimmer text-label-stronger rounded-full border px-3 py-1 text-xs">
                  {resolveMessage("sharepoint_wrapper_group", "Group")}
                </span>
                {#each getGroupCountBadges(sourceGroup.counts) as badge, index (`group-${sourceGroup.key}-${index}`)}
                  <span class="label-blue border-label-default bg-label-dimmer text-label-stronger rounded-full border px-3 py-1 text-sm">
                    {badge}
                  </span>
                {/each}
                {#if sourceGroup.isWrapperGroup && sourceGroup.wrapperId}
                  <SharePointWrapperActions
                    wrapperId={sourceGroup.wrapperId}
                    wrapperName={sourceGroup.wrapperName ?? sourceGroup.title}
                    itemCount={sourceGroup.itemCount}
                    canEdit={sourceGroup.canEditWrapper}
                    canDelete={sourceGroup.canDeleteWrapper}
                  />
                {/if}
              </div>
            </svelte:fragment>
          </Table.Group>
        {/each}
        {#if section.hasUngroupedSharepoint}
          <Table.Group
            title={getUngroupedItemsLabel()}
            filterFn={createUngroupedSharepointFilter(
              section.groupedSharepointIds,
              section.embeddingModel.id
            )}
          >
            <svelte:fragment slot="title-prefix">
              <span
                aria-hidden="true"
                class="border-label-default inline-block h-3 w-3 shrink-0 rounded-bl border-b border-l"
              ></span>
            </svelte:fragment>
          </Table.Group>
        {/if}
        {#if section.hasNonSharepoint}
          <Table.Group
            title={getOtherIntegrationsLabel()}
            filterFn={createNonSharepointFilter(section.embeddingModel.id)}
          >
            <svelte:fragment slot="title-prefix">
              <span
                aria-hidden="true"
                class="border-label-default inline-block h-3 w-3 shrink-0 rounded-bl border-b border-l"
              ></span>
            </svelte:fragment>
          </Table.Group>
        {/if}
      {/if}
    {/each}
  {:else if $useSharepointWrapperGroups}
    {#each $sharepointWrapperGroups as sourceGroup (sourceGroup.key)}
      <Table.Group
        title={sourceGroup.title}
        filterFn={createSharePointWrapperFilter(sourceGroup.itemIds)}
      >
        <svelte:fragment slot="title-suffix">
          <div class="flex items-center gap-2">
            <span class="label-neutral border-label-default bg-label-dimmer text-label-stronger rounded-full border px-3 py-1 text-xs">
              {resolveMessage("sharepoint_wrapper_group", "Group")}
            </span>
            {#each getGroupCountBadges(sourceGroup.counts) as badge, index (`group-${sourceGroup.key}-${index}`)}
              <span class="label-blue border-label-default bg-label-dimmer text-label-stronger rounded-full border px-3 py-1 text-sm">
                {badge}
              </span>
            {/each}
            {#if sourceGroup.isWrapperGroup && sourceGroup.wrapperId}
              <SharePointWrapperActions
                wrapperId={sourceGroup.wrapperId}
                wrapperName={sourceGroup.wrapperName ?? sourceGroup.title}
                itemCount={sourceGroup.itemCount}
                canEdit={sourceGroup.canEditWrapper}
                canDelete={sourceGroup.canDeleteWrapper}
              />
            {/if}
          </div>
        </svelte:fragment>
      </Table.Group>
    {/each}
    {#if $hasUngroupedSharepointKnowledge}
      <Table.Group filterFn={createUngroupedSharepointFilter($sharepointGroupedItemIds)}></Table.Group>
    {/if}
    {#if $hasNonSharepointKnowledge}
      <Table.Group
        title={getOtherIntegrationsLabel()}
        filterFn={createNonSharepointFilter()}
      ></Table.Group>
    {/if}
  {:else}
    <Table.Group></Table.Group>
  {/if}
</Table.Root>
