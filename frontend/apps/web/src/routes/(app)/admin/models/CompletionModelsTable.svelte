<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import type { CompletionModel, ModelProviderPublic } from "@intric/intric-js";
  import { Table } from "@intric/ui";
  import { createRender } from "svelte-headless-table";
  import ModelEnabledSwitch from "./ModelEnableSwitch.svelte";
  import {
    default as ModelLabels,
    getLabels
  } from "$lib/features/ai-models/components/ModelLabels.svelte";
  import ModelActions from "./ModelActions.svelte";
  import ModelNameCell from "./ModelNameCell.svelte";
  import ModelClassificationPreview from "$lib/features/security-classifications/components/ModelClassificationPreview.svelte";
  import ProviderActions from "./ProviderActions.svelte";
  import ProviderGlyph from "./components/ProviderGlyph.svelte";
  import ProviderStatusBadge from "./components/ProviderStatusBadge.svelte";
  import { getChartColour } from "$lib/features/ai-models/components/ModelNameAndVendor.svelte";
  import { m } from "$lib/paraglide/messages";

  import { writable, type Writable } from "svelte/store";
  import { Button } from "@intric/ui";
  import { Plus } from "lucide-svelte";
  import ProviderDialog from "./ProviderDialog.svelte";
  import { AddWizard } from "./AddWizard/index.js";
  import PageEmptyState from "./components/PageEmptyState.svelte";
  import ProviderEmptyState from "./components/ProviderEmptyState.svelte";

  export let completionModels: CompletionModel[];
  export let providers: ModelProviderPublic[] = [];
  export let addModelDialogOpen: Writable<boolean> | undefined = undefined;
  export let preSelectedProviderId: Writable<string | null> | undefined = undefined;

  const addWizardOpen = writable(false);
  // Pre-selected provider for "Add Model" from provider dropdown
  let wizardPreSelectedProviderId: string | null = null;

  // Track provider being edited (for credential icon click -> edit provider)
  let editingProvider: ModelProviderPublic | null = null;
  const editProviderDialogOpen = writable(false);

  // Backend returns both global and tenant models
  // Filter to show only tenant models in UI
  $: filteredModels = completionModels.filter(m => m.provider_id != null);

  const table = Table.createWithResource(filteredModels);

  // Build columns dynamically based on feature flags
  $: columns = [
    table.column({
      accessor: (model) => model,
      header: m.name(),
      cell: (item) => {
        return createRender(ModelNameCell, { model: item.value });
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
        return createRender(ModelEnabledSwitch, { model: item.value, type: "completionModel" });
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
        return createRender(ModelActions, {
          model: item.value,
          type: "completionModel",
          completionModels: filteredModels
        });
      }
    })
  ];

  $: viewModel = table.createViewModel(columns);

  // Group by provider_id for tenant models
  function createGroupFilter(groupKey: string) {
    return function (model: CompletionModel) {
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
   * Get the model count for a given provider.
   */
  function getModelCountForProvider(providerId: string): number {
    return filteredModels.filter(model => model.provider_id === providerId).length;
  }

  /**
   * Handle "Add Model" action from provider dropdown.
   * Opens the add model dialog with this provider pre-selected.
   */
  function handleAddModelToProvider(providerId: string) {
    wizardPreSelectedProviderId = providerId;
    addWizardOpen.set(true);
  }

  /**
   * Handle editing a provider (e.g., when clicking the credential icon).
   * Opens the ProviderDialog in edit mode.
   */
  function handleEditProvider(provider: ModelProviderPublic) {
    editingProvider = provider;
    editProviderDialogOpen.set(true);
  }

  $: groups = listGroups(providers);
  $: table.update(filteredModels);</script>

{#if providers.length === 0}
  <PageEmptyState on:addProvider={() => { wizardPreSelectedProviderId = null; addWizardOpen.set(true); }} />
{:else}
<div class="flex flex-col gap-4">
  <Table.Root {viewModel} resourceName={m.resource_models()} displayAs="list" showEmptyGroups>
    {#each groups as group (group.key)}
      {@const provider = getProviderForGroup(group.key)}
      <Table.Group filterFn={createGroupFilter(group.key)} title=" ">
        <svelte:fragment slot="title-prefix">
          {#if provider}
            <!-- Glyph + Name as unified clickable button to edit provider -->
            <button
              class="flex items-center gap-3 mr-1 group cursor-pointer rounded-lg transition-colors duration-150 focus:outline-none focus:ring-2 focus:ring-accent-default focus:ring-offset-2"
              on:click|stopPropagation={() => handleEditProvider(provider)}
              title={m.edit_provider()}
            >
              <span class="transition-transform duration-150 group-hover:scale-105">
                <ProviderGlyph providerType={provider.provider_type} size="md" />
              </span>
              <span class="font-medium text-primary group-hover:text-accent-default group-hover:underline underline-offset-2 decoration-accent-default/50 transition-colors">
                {provider.name}
              </span>
            </button>
          {:else}
            <div class="flex items-center gap-2 mr-2">
              <div
                class="h-3 w-3 rounded-full border border-stronger"
                style="background: var(--{getChartColour(group.name)})"
              ></div>
              <span class="font-medium text-primary">{group.name}</span>
            </div>
          {/if}
        </svelte:fragment>
        <svelte:fragment slot="title-suffix">
          <div class="flex items-center gap-2">
            {#if provider}
              {@const modelCount = getModelCountForProvider(provider.id)}
              <!-- Model count with bullet separator -->
              <span class="text-xs text-muted tabular-nums opacity-70">
                •  {modelCount === 1 ? m.provider_model_count_one({ count: modelCount }) : m.provider_model_count_other({ count: modelCount })}
              </span>
              <!-- Visual separator between info and actions -->
              <span class="w-px h-4 bg-border-dimmer"></span>
              <ProviderStatusBadge {provider} />
              <ProviderActions
                {provider}
                onAddModel={handleAddModelToProvider}
              />
            {/if}
          </div>
        </svelte:fragment>
        <svelte:fragment slot="empty">
          {#if provider}
            <ProviderEmptyState
              providerId={provider.id}
              on:addModel={(e) => handleAddModelToProvider(e.detail.providerId)}
            />
          {:else}
            <div class="text-sm text-muted/80 py-3 px-4 bg-surface-dimmer/50 rounded-lg border border-dashed border-dimmer">
              {m.no_models_in_provider()}
            </div>
          {/if}
        </svelte:fragment>
      </Table.Group>
    {/each}
  </Table.Root>

  <div class="flex justify-center pt-8 pb-6 mt-4 border-t border-dimmer">
    <Button variant="outlined" on:click={() => { wizardPreSelectedProviderId = null; addWizardOpen.set(true); }}>
      <Plus class="w-4 h-4 mr-2" />
      {m.add_provider()}
    </Button>
  </div>
</div>
{/if}

<!-- Add Provider & Models Wizard -->
<AddWizard
  openController={addWizardOpen}
  {providers}
  modelType="completion"
  preSelectedProviderId={wizardPreSelectedProviderId}
/>

<!-- Edit Provider Dialog -->
<ProviderDialog openController={editProviderDialogOpen} provider={editingProvider} />
