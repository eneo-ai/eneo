<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { EmbeddingModel } from "@intric/intric-js";
  import { Table } from "@intric/ui";
  import { createRender } from "svelte-headless-table";
  import ModelEnableSwitch from "./ModelEnableSwitch.svelte";
  import {
    default as ModelLabels,
    getLabels
  } from "$lib/features/ai-models/components/ModelLabels.svelte";
  import { modelOrgs } from "$lib/features/ai-models/components/ModelNameAndVendor.svelte";
  import ModelCardDialog from "$lib/features/ai-models/components/ModelCardDialog.svelte";
  import ModelActions from "./ModelActions.svelte";
  import ModelClassificationPreview from "$lib/features/security-classifications/components/ModelClassificationPreview.svelte";
  import { m } from "$lib/paraglide/messages";

  export let embeddingModels: EmbeddingModel[];
  const table = Table.createWithResource(embeddingModels);

  const viewModel = table.createViewModel([
    table.column({
      accessor: (model) => model,
      header: m.name(),
      cell: (item) => {
        return createRender(ModelCardDialog, { model: item.value, includeTrigger: true });
      },
      plugins: {
        sort: {
          getSortValue(value) {
            return value.nickname;
          }
        },
        tableFilter: {
          getFilterValue(value) {
            return `${value.nickname} ${value.org}`;
          }
        }
      }
    }),
    table.column({
      accessor: (model) => model,
      header: m.enabled(),
      cell: (item) => {
        return createRender(ModelEnableSwitch, { model: item.value, type: "embeddingModel" });
      },
      plugins: {
        sort: {
          getSortValue(value) {
            return value.is_org_enabled ? 1 : 0;
          }
        }
      }
    }),
    table.column({
      accessor: (model) => model,
      header: m.details(),
      cell: (item) => {
        return createRender(ModelLabels, { model: item.value });
      },
      plugins: {
        sort: {
          disable: true
        },
        tableFilter: {
          getFilterValue(value) {
            const labels = getLabels(value).flatMap((label) => {
              return label.label;
            });
            return labels.join(" ");
          }
        }
      }
    }),

    table.column({
      accessor: (model) => model,
      header: m.security(),
      cell: (item) => {
        return createRender(ModelClassificationPreview, { model: item.value });
      },
      plugins: {
        sort: {
          getSortValue(value) {
            return value.security_classification?.security_level ?? 0;
          }
        },
        tableFilter: {
          getFilterValue(value) {
            return value.security_classification?.name ?? "";
          }
        }
      }
    }),

    table.columnActions({
      cell: (item) => {
        return createRender(ModelActions, { model: item.value, type: "embeddingModel" });
      }
    })
  ]);

  function createOrgFilter(org: string | undefined | null) {
    return function (model: EmbeddingModel) {
      return model.org === org;
    };
  }

  $: table.update(embeddingModels);
</script>

<Table.Root {viewModel} resourceName="model" displayAs="list">
  {#each Object.entries(modelOrgs) as [org] (org)}
    <Table.Group filterFn={createOrgFilter(org)} title={org} />
  {/each}
</Table.Root>
