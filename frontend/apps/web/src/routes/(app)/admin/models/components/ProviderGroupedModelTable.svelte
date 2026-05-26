<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  Generic provider-grouped table used by all three model-type tabs
  (completion / embedding / transcription). Replaces three near-identical
  copies that drifted apart over time. Per-type behaviour is limited to:

    - the deprecation banner — only completion models carry deprecation_date
    - passing `completionModels` through to ModelNameCell + ModelActions
      (used by the migrate flow, which is completion-only)

  All other concerns — grouping, "Add model" CTA, empty state — are
  identical and live here.
-->

<script lang="ts" generics="M extends CompletionModel | EmbeddingModel | TranscriptionModel">
  import type {
    CompletionModel,
    EmbeddingModel,
    ModelProviderPublic,
    TranscriptionModel
  } from "@intric/intric-js";
  import { Table } from "@intric/ui";
  import { Button } from "$lib/components/ui/button/index.js";
  import { createRender } from "svelte-headless-table";
  import { writable } from "svelte/store";
  import { Plus, TriangleAlert, Clock } from "lucide-svelte";

  import { m } from "$lib/paraglide/messages";
  import {
    default as ModelStatusIcons,
    getStatusIcons
  } from "$lib/features/ai-models/components/ModelStatusIcons.svelte";
  import { getChartColour } from "$lib/features/ai-models/components/ModelNameAndVendor.svelte";
  import { getDeprecationStatus } from "$lib/features/ai-models/formatModelStats";
  import { getSecurityContext } from "$lib/features/security-classifications/SecurityContext";

  import ModelEnableSwitch from "../ModelEnableSwitch.svelte";
  import ModelActions from "../ModelActions.svelte";
  import ModelClassificationCell from "../ModelClassificationCell.svelte";
  import ModelNameCell from "../ModelNameCell.svelte";
  import ProviderActions from "../ProviderActions.svelte";
  import ProviderDialog from "../ProviderDialog.svelte";
  import ProviderGlyph from "./ProviderGlyph.svelte";
  import PageEmptyState from "./PageEmptyState.svelte";
  import ProviderEmptyState from "./ProviderEmptyState.svelte";
  import { AddWizard } from "../AddWizard/index.js";

  type ModelTypeKey = "completionModel" | "embeddingModel" | "transcriptionModel";
  type WizardModelType = "completion" | "embedding" | "transcription";

  const wizardModelTypeFor: Record<ModelTypeKey, WizardModelType> = {
    completionModel: "completion",
    embeddingModel: "embedding",
    transcriptionModel: "transcription"
  };

  export let models: M[];
  export let providers: ModelProviderPublic[] = [];
  export let favoriteProviders: string[] = [];
  export let modelType: ModelTypeKey;

  function isMigratedModel(model: M): boolean {
    return "migrated_to_model_id" in model && !!model.migrated_to_model_id;
  }

  $: tenantModels = models.filter((model) => model.provider_id != null && !isMigratedModel(model));
  $: wizardModelType = wizardModelTypeFor[modelType];
  $: showDeprecationBanner = modelType === "completionModel";
  // Show the classification column only when the tenant has configured at
  // least one classification — otherwise the column would be all em-dashes.
  // Read once at mount: classifications are managed on a different route
  // (/admin/security-classifications), so any change forces a navigation back
  // here, which remounts this component with a fresh `getSecurityContext()`
  // value seeded by the parent page's `setSecurityContext(data.security…)`.
  // No same-mount mutation of classifications happens, so a const is enough.
  const hasClassifications = getSecurityContext().security_classifications.length > 0;

  // --- Wizard / edit-provider dialogs ----------------------------------
  const addWizardOpen = writable(false);
  const editProviderDialogOpen = writable(false);
  let wizardPreSelectedProviderId: string | null = null;
  let editingProvider: ModelProviderPublic | null = null;

  function openAddProvider() {
    wizardPreSelectedProviderId = null;
    addWizardOpen.set(true);
  }
  function handleAddModelToProvider(providerId: string) {
    wizardPreSelectedProviderId = providerId;
    addWizardOpen.set(true);
  }
  function handleEditProvider(provider: ModelProviderPublic) {
    editingProvider = provider;
    editProviderDialogOpen.set(true);
  }

  // --- Table columns ----------------------------------------------------
  const table = Table.createWithResource(tenantModels);

  $: columns = [
    table.column({
      accessor: (model: M) => model,
      header: m.name(),
      cell: (item) =>
        createRender(ModelNameCell, {
          model: item.value,
          type: modelType,
          completionModels:
            modelType === "completionModel" ? (tenantModels as unknown as CompletionModel[]) : []
        }),
      plugins: {
        sort: { getSortValue: (value) => value.nickname ?? "" },
        tableFilter: { getFilterValue: (value) => `${value.nickname ?? ""} ${value.org ?? ""}` }
      }
    }),

    table.column({
      accessor: (model: M) => model,
      header: m.enabled(),
      cell: (item) => createRender(ModelEnableSwitch, { model: item.value, type: modelType }),
      plugins: { sort: { getSortValue: (value) => (value.is_org_enabled ? 1 : 0) } }
    }),

    ...(hasClassifications
      ? [
          table.column({
            accessor: (model: M) => model,
            header: m.security_classification(),
            cell: (item) => createRender(ModelClassificationCell, { model: item.value }),
            plugins: {
              sort: {
                getSortValue: (value) => value.security_classification?.security_level ?? -1
              },
              tableFilter: {
                getFilterValue: (value) => value.security_classification?.name ?? ""
              }
            }
          })
        ]
      : []),

    table.column({
      accessor: (model: M) => model,
      header: m.details(),
      cell: (item) => createRender(ModelStatusIcons, { model: item.value }),
      plugins: {
        sort: { disable: true },
        tableFilter: {
          getFilterValue: (value) =>
            getStatusIcons(value)
              .flatMap((icon) => icon.ariaLabel)
              .join(" ")
        }
      }
    }),

    table.columnActions({
      cell: (item) =>
        createRender(ModelActions, {
          model: item.value,
          type: modelType,
          completionModels:
            modelType === "completionModel" ? (tenantModels as unknown as CompletionModel[]) : []
        })
    })
  ];

  $: viewModel = table.createViewModel(columns);
  $: table.update(tenantModels);

  // --- Provider grouping ------------------------------------------------
  // Only show providers that already have at least one model in this
  // section. A provider that the tenant configured for completion but
  // hasn't given any embedding models stays hidden from the embedding
  // tab — the user reaches it via "Add Provider", which lets them pick
  // an existing provider in the wizard and add a model to it.
  $: visibleProviders = providers.filter((p) =>
    tenantModels.some((model) => model.provider_id === p.id)
  );
  // True when the user has providers configured but none of them have a
  // model in the current section. Surfaces a focused hint with the same
  // "Add Provider" CTA so the wizard can take it from there.
  $: noModelsForThisType = providers.length > 0 && visibleProviders.length === 0;

  $: groups = visibleProviders.map((provider) => ({
    key: provider.id,
    name: provider.name,
    modelCount: tenantModels.filter((model) => model.provider_id === provider.id).length
  }));

  function groupFilterFor(providerId: string) {
    return (model: M) => model.provider_id === providerId;
  }
  function getProviderForGroup(providerId: string) {
    return providers.find((p) => p.id === providerId);
  }
  function getModelCountForProvider(providerId: string) {
    return tenantModels.filter((model) => model.provider_id === providerId).length;
  }

  // Default to expanded for non-empty groups, collapsed for empty ones.
  let groupOpenState: Record<string, boolean> = {};
  $: {
    for (const group of groups) {
      if (!(group.key in groupOpenState)) {
        groupOpenState[group.key] = group.modelCount > 0;
      }
    }
  }

  // --- Banner counts (completion only) ---------------------------------
  $: deprecationCounts = !showDeprecationBanner
    ? { deprecated: 0, retiring: 0 }
    : tenantModels.reduce(
        (acc, model) => {
          const status = getDeprecationStatus(
            "deprecation_date" in model ? model : { deprecation_date: null }
          );
          if (status.kind === "deprecated") acc.deprecated += 1;
          else if (status.kind === "retiring") acc.retiring += 1;
          return acc;
        },
        { deprecated: 0, retiring: 0 }
      );
  $: deprecatedCount = deprecationCounts.deprecated;
  $: retiringCount = deprecationCounts.retiring;
</script>

{#if providers.length === 0}
  <PageEmptyState onAddProvider={openAddProvider} />
{:else if noModelsForThisType}
  <PageEmptyState
    onAddProvider={openAddProvider}
    title={m.no_models_for_this_type_title()}
    description={m.no_models_for_this_type_description()}
    ctaLabel={m.add_provider()}
    helper=""
  />
{:else}
  <div class="flex flex-col gap-4">
    {#if deprecatedCount > 0}
      <div
        class="border-negative-default/20 bg-negative-dimmer/30 text-negative-stronger mx-3 mt-3 flex items-center gap-3 rounded-lg border px-4 py-3 text-sm"
        role="alert"
      >
        <TriangleAlert size={16} class="flex-shrink-0" aria-hidden="true" />
        <span>
          {deprecatedCount === 1
            ? m.models_deprecated_banner_one({ count: deprecatedCount })
            : m.models_deprecated_banner_other({ count: deprecatedCount })}
        </span>
      </div>
    {/if}
    {#if retiringCount > 0}
      <div
        class="border-warning-default/20 bg-warning-dimmer/30 text-warning-stronger mx-3 flex items-center gap-3 rounded-lg border px-4 py-3 text-sm {deprecatedCount >
        0
          ? ''
          : 'mt-3'}"
        role="alert"
      >
        <Clock size={16} class="flex-shrink-0" aria-hidden="true" />
        <span>
          {retiringCount === 1
            ? m.models_retiring_banner_one({ count: retiringCount })
            : m.models_retiring_banner_other({ count: retiringCount })}
        </span>
      </div>
    {/if}

    <Table.Root {viewModel} resourceName={m.resource_models()} displayAs="list" showEmptyGroups>
      {#each groups as group (group.key)}
        {@const provider = getProviderForGroup(group.key)}
        <Table.Group
          filterFn={groupFilterFor(group.key)}
          title=" "
          open={groupOpenState[group.key] ?? true}
          on:openChange={(e) => {
            groupOpenState[group.key] = e.detail.open;
          }}
        >
          <svelte:fragment slot="title-prefix">
            {#if provider}
              <button
                class="group focus:ring-accent-default mr-1 flex cursor-pointer items-center gap-3 rounded-lg transition-colors duration-150 focus:ring-2 focus:ring-offset-2 focus:outline-none"
                on:click|stopPropagation={() => handleEditProvider(provider)}
                title={m.edit_provider()}
              >
                <span class="transition-transform duration-150 group-hover:scale-105">
                  <ProviderGlyph providerType={provider.provider_type} size="md" />
                </span>
                <span
                  class="text-primary group-hover:text-accent-default decoration-accent-default/50 font-medium underline-offset-2 transition-colors group-hover:underline"
                >
                  {provider.name}
                </span>
              </button>
            {:else}
              <div class="mr-2 flex items-center gap-2">
                <div
                  class="border-stronger h-3 w-3 rounded-full border"
                  style="background: var(--{getChartColour(group.name)})"
                ></div>
                <span class="text-primary font-medium">{group.name}</span>
              </div>
            {/if}
          </svelte:fragment>

          <svelte:fragment slot="title-suffix">
            <div class="flex items-center gap-2">
              {#if provider}
                {@const modelCount = getModelCountForProvider(provider.id)}
                <span class="text-muted text-xs tabular-nums opacity-70">
                  • {modelCount === 1
                    ? m.provider_model_count_one({ count: modelCount })
                    : m.provider_model_count_other({ count: modelCount })}
                </span>
                <span class="bg-border-dimmer h-4 w-px"></span>
                <button
                  class="text-muted hover:bg-hover-dimmer hover:text-primary focus:ring-accent-default flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition-colors duration-150 focus:ring-1 focus:outline-none"
                  on:click|stopPropagation={() => handleAddModelToProvider(provider.id)}
                  title={m.add_model()}
                >
                  <Plus class="h-3.5 w-3.5" />
                  {m.add_model()}
                </button>
                <ProviderActions {provider} onEditProvider={handleEditProvider} />
              {/if}
            </div>
          </svelte:fragment>

          <svelte:fragment slot="empty">
            {#if provider}
              <ProviderEmptyState providerId={provider.id} onAddModel={handleAddModelToProvider} />
            {:else}
              <div
                class="text-muted/80 bg-surface-dimmer/50 border-dimmer rounded-lg border border-dashed px-4 py-3 text-sm"
              >
                {m.no_models_in_provider()}
              </div>
            {/if}
          </svelte:fragment>
        </Table.Group>
      {/each}
    </Table.Root>

    <div class="border-dimmer mt-4 flex justify-center border-t pt-8 pb-6">
      <Button variant="outline" onclick={openAddProvider}>
        <Plus />
        {m.add_provider()}
      </Button>
    </div>
  </div>
{/if}

<AddWizard
  openController={addWizardOpen}
  {providers}
  {favoriteProviders}
  modelType={wizardModelType}
  preSelectedProviderId={wizardPreSelectedProviderId}
/>

<ProviderDialog openController={editProviderDialogOpen} provider={editingProvider} />

<style>
  :global(tr:has([data-status="deprecated"])) {
    background-color: var(--color-negative-dimmer) !important;
  }
  :global(tr:has([data-status="retiring"])) {
    background-color: var(--color-warning-dimmer) !important;
  }
</style>
