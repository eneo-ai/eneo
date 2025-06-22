<script lang="ts">
  import { Table } from "@intric/ui";
  import WebsiteActions from "./WebsiteActions.svelte";
  import { createRender } from "svelte-headless-table";
  import WebsiteStatus from "./WebsiteStatus.svelte";
  import WebsiteSync from "./WebsiteSync.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { derived } from "svelte/store";
  import type { WebsiteSparse } from "@intric/intric-js";
  import { IconWeb } from "@intric/icons/web";
  import { formatWebsiteName } from "$lib/core/formatting/formatWebsiteName";
  import { m } from "$lib/paraglide/messages";

  const {
    state: { currentSpace }
  } = getSpacesManager();

  const websites = derived(currentSpace, ($currentSpace) => $currentSpace.knowledge.websites);
  const embeddingModels = derived(currentSpace, ($currentSpace) => {
    const modelsInSpace = $currentSpace.embedding_models.map((model) => model.id);
    const modelsInWebsites = $currentSpace.knowledge.websites.map((website) => {
      return {
        ...website.embedding_model,
        inSpace: modelsInSpace.includes(website.embedding_model.id)
      };
    });
    // Need to remove duplicates from array
    const models = modelsInWebsites.filter(
      // will be true if this is the first time the model is mentioned
      (curr, idx, models) => idx === models.findIndex((other) => other.id === curr.id)
    );
    return models;
  });
  const disabledModelInUse = derived(embeddingModels, ($embeddingModels) => {
    return [...$embeddingModels].findIndex((model) => model.inSpace === false) > -1;
  });

  const table = Table.createWithStore(websites);

  const viewModel = table.createViewModel([
    table.column({
      accessor: (item) => item,
      header: m.website(),
      cell: (item) => {
        return createRender(Table.PrimaryCell, {
          link: `/spaces/${$currentSpace.routeId}/knowledge/websites/${item.value.id}`,
          label: formatWebsiteName(item.value),
          tooltip: item.value.url,
          customClass: "max-w-64",
          icon: IconWeb
        });
      },
      plugins: {
        tableFilter: {
          getFilterValue(value) {
            return value.name + "_____" + value.url;
          }
        },
        sort: {
          getSortValue(value) {
            return formatWebsiteName(value);
          }
        }
      }
    }),

    table.column({
      accessor: "url",
      header: m.link(),
      cell: (item) => {
        return createRender(Table.ButtonCell, {
          link: item.value,
          label: m.go_to_website(),
          linkIsExternal: true
        });
      }
    }),

    table.column({
      accessor: (item) => item,
      header: m.status(),
      cell: (item) => {
        return createRender(WebsiteStatus, {
          website: item.value
        });
      },
      plugins: {
        sort: {
          getSortValue(value) {
            return value.latest_crawl?.created_at ?? null;
          }
        },
        tableFilter: {
          getFilterValue(value) {
            return value.latest_crawl?.finished_at ?? null;
          }
        }
      }
    }),

    table.column({
      accessor: "update_interval",
      header: m.auto_updates(),
      cell: (item) => {
        return createRender(WebsiteSync, {
          updateInterval: item.value
        });
      }
    }),

    table.columnActions({
      cell: (item) => {
        return createRender(WebsiteActions, { website: item.value });
      }
    })
  ]);

  function createModelFilter(embeddingModel: { id: string }) {
    return function (website: WebsiteSparse) {
      return website.embedding_model.id === embeddingModel.id;
    };
  }
</script>

<Table.Root {viewModel} resourceName="website">
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
