<script lang="ts">
  import { Table } from "@intric/ui";
  import { createRender } from "svelte-headless-table";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { derived } from "svelte/store";
  import type { GroupSparse } from "@intric/intric-js";
  import IntegrationNameCell from "./IntegrationNameCell.svelte";
  import IntegrationActions from "./IntegrationActions.svelte";
  import { integrationData } from "$lib/features/integrations/IntegrationData";
  import { m } from "$lib/paraglide/messages";

  const {
    state: { currentSpace }
  } = getSpacesManager();

  const knowledge = derived(
    currentSpace,
    ($currentSpace) => $currentSpace.knowledge.integrationKnowledge
  );

  const embeddingModels = derived(currentSpace, ($currentSpace) => {
    const modelsInSpace = $currentSpace.embedding_models.map((model) => model.id);
    const modelsInIntegrationKnowledge = $currentSpace.knowledge.integrationKnowledge.map(
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

  const table = Table.createWithStore(knowledge);

  const viewModel = table.createViewModel([
    table.column({
      header: m.name(),
      accessor: (item) => item,
      cell: (item) => {
        return createRender(IntegrationNameCell, {
          knowledge: item.value
        });
      }
    }),

    table.column({
      accessor: (item) => item,
      header: m.link(),
      cell: (item) => {
        return createRender(Table.ButtonCell, {
          link: item.value.url ?? "",
          label: integrationData[item.value.integration_type].previewLinkLabel,
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

  function createModelFilter(embeddingModel: { id: string }) {
    return function (collection: GroupSparse) {
      return collection.embedding_model.id === embeddingModel.id;
    };
  }
</script>

<Table.Root {viewModel} resourceName="integration">
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
