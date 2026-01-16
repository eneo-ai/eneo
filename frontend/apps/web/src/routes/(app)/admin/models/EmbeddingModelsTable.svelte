<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { EmbeddingModel, ModelProviderPublic } from "@intric/intric-js";
  import { Table } from "@intric/ui";
  import { createRender } from "svelte-headless-table";
  import ModelEnableSwitch from "./ModelEnableSwitch.svelte";
  import {
    default as ModelLabels,
    getLabels
  } from "$lib/features/ai-models/components/ModelLabels.svelte";
  import ModelCardDialog from "$lib/features/ai-models/components/ModelCardDialog.svelte";
  import ModelActions from "./ModelActions.svelte";
  import ModelClassificationPreview from "$lib/features/security-classifications/components/ModelClassificationPreview.svelte";
  import ProviderCredentialIcon from "$lib/features/credentials/components/ProviderCredentialIcon.svelte";
  import ProviderActions from "./ProviderActions.svelte";
  import ProviderDialog from "./ProviderDialog.svelte";
  import { m } from "$lib/paraglide/messages";
  import { writable, type Writable } from "svelte/store";
  import { Button } from "@intric/ui";
  import { Plus } from "lucide-svelte";

  export let embeddingModels: EmbeddingModel[];
  export let providers: ModelProviderPublic[] = [];
  export let addModelDialogOpen: Writable<boolean> | undefined = undefined;
  export let preSelectedProviderId: Writable<string | null> | undefined = undefined;

  const addProviderDialogOpen = writable(false);

  // Track provider being edited
  let editingProvider: ModelProviderPublic | null = null;
  const editProviderDialogOpen = writable(false);

  // Backend returns both global and tenant models
  // Filter to show only tenant models in UI
  $: filteredModels = embeddingModels.filter(m => m.provider_id != null);

  const table = Table.createWithResource(filteredModels);

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

  // Group by provider_id for tenant models
  function createGroupFilter(groupKey: string) {
    return function (model: EmbeddingModel) {
      return model.provider_id === groupKey;
    };
  }

  function listGroups(providerList: ModelProviderPublic[]): Array<{ key: string; name: string }> {
    // Show all providers, including those without models
    return providerList.map(provider => ({
      key: provider.id,
      name: provider.name
    }));
  }

  /**
   * Get the full provider object for a given group.
   */
  function getProviderForGroup(groupKey: string): ModelProviderPublic | undefined {
    return providers.find(p => p.id === groupKey);
  }

  /**
   * Handle "Add Model" action from provider dropdown.
   * Opens the add model dialog with this provider pre-selected.
   */
  function handleAddModelToProvider(providerId: string) {
    preSelectedProviderId?.set(providerId);
    addModelDialogOpen?.set(true);
  }

  /**
   * Handle editing a provider.
   */
  function handleEditProvider(provider: ModelProviderPublic) {
    editingProvider = provider;
    editProviderDialogOpen.set(true);
  }

  $: groups = listGroups(providers);
  $: table.update(filteredModels);
</script>

<div class="flex flex-col gap-4">
  <Table.Root {viewModel} resourceName={m.resource_models()} displayAs="list">
    {#each groups as group (group.key)}
      {@const provider = getProviderForGroup(group.key)}
      <Table.Group filterFn={createGroupFilter(group.key)} title={group.name}>
        <svelte:fragment slot="title-suffix">
          <div class="flex items-center gap-2">
            {#if provider}
              <ProviderCredentialIcon
                {provider}
                onEdit={() => handleEditProvider(provider)}
              />
              <ProviderActions
                {provider}
                onAddModel={handleAddModelToProvider}
              />
            {/if}
          </div>
        </svelte:fragment>
        <svelte:fragment slot="empty">
          <span class="text-sm text-muted">{m.no_models_in_provider()}</span>
        </svelte:fragment>
      </Table.Group>
    {/each}
  </Table.Root>

  <div class="flex justify-center pb-4">
    <Button variant="outlined" on:click={() => addProviderDialogOpen.set(true)}>
      <Plus class="w-4 h-4 mr-2" />
      {m.add_provider()}
    </Button>
  </div>
</div>

<!-- Add Provider Dialog -->
<ProviderDialog openController={addProviderDialogOpen} />

<!-- Edit Provider Dialog -->
<ProviderDialog openController={editProviderDialogOpen} provider={editingProvider} />
