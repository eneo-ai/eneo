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
  import ModelCardDialog from "$lib/features/ai-models/components/ModelCardDialog.svelte";
  import ModelActions from "./ModelActions.svelte";
  import ModelClassificationPreview from "$lib/features/security-classifications/components/ModelClassificationPreview.svelte";
  import ProviderCredentialIcon from "$lib/features/credentials/components/ProviderCredentialIcon.svelte";
  import { m } from "$lib/paraglide/messages";
  import { browser } from "$app/environment";
  import type { Writable } from "svelte/store";
  import { Button } from "@intric/ui";
  import { Plus } from "lucide-svelte";

  export let embeddingModels: EmbeddingModel[];
  export let providers: any[] = [];
  export let credentials:
    | {
        provider: string;
        masked_key: string;
        config: Record<string, any>;
      }[]
    | undefined = undefined;
  export let tenantCredentialsEnabled: boolean = false;
  export let tenantModelsEnabled: boolean = false;
  export let addModelDialogOpen: Writable<boolean> | undefined = undefined;

  // When tenant_models_enabled, backend returns both global and tenant models
  // Filter to show only tenant models in UI
  $: filteredModels = tenantModelsEnabled
    ? embeddingModels.filter(m => m.provider_id != null)
    : embeddingModels;

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

  function createGroupFilter(groupKey: string) {
    return function (model: EmbeddingModel) {
      if (tenantModelsEnabled) {
        return model.provider_id === groupKey;
      } else {
        return model.org === groupKey;
      }
    };
  }

  function listGroups(models: EmbeddingModel[]): Array<{ key: string; name: string }> {
    if (tenantModelsEnabled) {
      const uniqueProviders = new Set<string>();
      for (const model of models) {
        if (model.provider_id) uniqueProviders.add(model.provider_id);
      }
      return Array.from(uniqueProviders).map(providerId => {
        const provider = providers.find(p => p.id === providerId);
        return {
          key: providerId,
          name: provider?.name || "Unknown Provider"
        };
      });
    } else {
      const uniqueOrgs = new Set<string>();
      for (const model of models) {
        if (model.org) uniqueOrgs.add(model.org);
      }
      return Array.from(uniqueOrgs).map(org => ({
        key: org,
        name: org
      }));
    }
  }

  /**
   * Get the credential provider ID for a given group.
   * For tenant models, returns the provider's credential type.
   * For global models, returns the model's credential_provider field.
   */
  function getProviderIdForGroup(groupKey: string): string | undefined {
    if (tenantModelsEnabled) {
      const provider = providers.find(p => p.id === groupKey);
      return provider?.type;
    } else {
      const model = embeddingModels.find((m) => m.org === groupKey);
      return model?.credential_provider;
    }
  }

  function getCredentialForGroup(groupKey: string, groupName: string) {
    if (!credentials) return undefined;

    const providerId = getProviderIdForGroup(groupKey);
    if (!providerId) return undefined;

    const cred = credentials.find((c) => c.provider.toLowerCase() === providerId.toLowerCase());
    if (!cred) return undefined;
    return {
      masked_key: cred.masked_key,
      config: cred.config
    };
  }

  $: groups = listGroups(filteredModels);
  $: table.update(filteredModels);
</script>

<div class="flex flex-col gap-4">
  <Table.Root {viewModel} resourceName={m.resource_models()} displayAs="list">
    {#each groups as group (group.key)}
      {@const providerId = getProviderIdForGroup(group.key)}
      <Table.Group filterFn={createGroupFilter(group.key)} title={group.name}>
        <svelte:fragment slot="title-suffix">
          {#if browser && tenantCredentialsEnabled && providerId}
            <ProviderCredentialIcon
              provider={providerId}
              displayName={group.name}
              credential={getCredentialForGroup(group.key, group.name)}
            />
          {/if}
        </svelte:fragment>
      </Table.Group>
    {/each}
  </Table.Root>

  {#if tenantModelsEnabled && addModelDialogOpen}
    <div class="flex justify-center pb-4">
      <Button variant="outlined" on:click={() => addModelDialogOpen?.set(true)}>
        <Plus class="w-4 h-4 mr-2" />
        Add Embedding Model
      </Button>
    </div>
  {/if}
</div>
