<script lang="ts">
  import { Table } from "@intric/ui";
  import { createRender } from "svelte-headless-table";
  import CollectionActions from "./CollectionActions.svelte";
  import CollectionFileLabels from "./CollectionFileLabels.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { derived } from "svelte/store";
  import type { GroupSparse } from "@intric/intric-js";
  import { IconCollections } from "@intric/icons/collections";
  import { m } from "$lib/paraglide/messages";

  const {
    state: { currentSpace }
  } = getSpacesManager();

  const collections = derived(currentSpace, ($currentSpace) => $currentSpace.knowledge.groups);
  const embeddingModels = derived(currentSpace, ($currentSpace) => {
    const modelsInSpace = $currentSpace.embedding_models.map((model) => model.id);
    const modelsInCollections = $currentSpace.knowledge.groups.map((collection) => {
      return {
        ...collection.embedding_model,
        inSpace: modelsInSpace.includes(collection.embedding_model.id)
      };
    });
    // Need to remove duplicates from array
    const models = modelsInCollections.filter(
      // will be true if this is the first time the model is mentioned
      (curr, idx, models) => idx === models.findIndex((other) => other.id === curr.id)
    );
    return models;
  });
  const disabledModelInUse = derived(embeddingModels, ($embeddingModels) => {
    return [...$embeddingModels].findIndex((model) => model.inSpace === false) > -1;
  });

  const table = Table.createWithStore(collections);

  const viewModel = table.createViewModel([
    table.columnPrimary({
      header: m.name(),
      value: (item) => item.name,
      cell: (item) => {
        return createRender(Table.PrimaryCell, {
          label: item.value.name,
          link: `/spaces/${$currentSpace.routeId}/knowledge/collections/${item.value.id}`,
          icon: IconCollections
        });
      }
    }),

    table.column({
      header: m.files_header(),
      accessor: (item) => item,
      cell: (item) =>
        createRender(CollectionFileLabels, {
          collection: item.value
        }),
      plugins: {
        sort: { getSortValue: (item) => item.metadata.num_info_blobs ?? 0 }
      }
    }),

    table.columnActions({
      cell: (item) => {
        return createRender(CollectionActions, {
          collection: item.value
        });
      }
    })
  ]);

  function createModelFilter(embeddingModel: { id: string }) {
    return function (collection: GroupSparse) {
      return collection.embedding_model.id === embeddingModel.id;
    };
  }
</script>

<Table.Root 
  {viewModel} 
  resourceName="collection"
  filterPlaceholder={m.filter_collections()}
  listText={m.list()}
  cardsText={m.cards()}
  noItemsMessage={m.there_are_currently_no_collections_configured()}
>
  {#if $embeddingModels.length > 1 || $currentSpace.embedding_models.length > 1 || $disabledModelInUse}
    {#each $embeddingModels as embeddingModel (embeddingModel.id)}
      <Table.Group
        title={embeddingModel.inSpace ? embeddingModel.name : embeddingModel.name + ` (${m.disabled()})`}
        filterFn={createModelFilter(embeddingModel)}
      ></Table.Group>
    {/each}
  {:else}
    <Table.Group></Table.Group>
  {/if}
</Table.Root>
