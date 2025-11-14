<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { CompletionModel } from "@intric/intric-js";
  import { Table } from "@intric/ui";
  import { createRender } from "svelte-headless-table";
  import ModelEnabledSwitch from "./ModelEnableSwitch.svelte";
  import {
    default as ModelLabels,
    getLabels
  } from "$lib/features/ai-models/components/ModelLabels.svelte";
  import ModelActions from "./ModelActions.svelte";
  import ModelCardDialog from "$lib/features/ai-models/components/ModelCardDialog.svelte";
  import ModelClassificationPreview from "$lib/features/security-classifications/components/ModelClassificationPreview.svelte";
  import ProviderCredentialIcon from "$lib/features/credentials/components/ProviderCredentialIcon.svelte";
  import AddProviderDialog from "$lib/features/credentials/components/AddProviderDialog.svelte";
  import { Button } from "@intric/ui";
  import { IconPlus } from "@intric/icons/plus";
  import { m } from "$lib/paraglide/messages";
  import { browser } from "$app/environment";
  import { writable } from "svelte/store";

  export let completionModels: CompletionModel[];
  export let credentials:
    | {
        provider: string;
        masked_key: string;
        config: Record<string, any>;
      }[]
    | undefined = undefined;
  export let tenantCredentialsEnabled: boolean = false;

  // Map lowercase provider IDs from credentials to proper ModelOrg enum values
  const PROVIDER_ID_TO_ORG: Record<string, string> = {
    openai: "OpenAI",
    anthropic: "Anthropic",
    azure: "Microsoft",
    berget: "Berget",
    gdm: "GDM",
    mistral: "Mistral",
    ovhcloud: "Microsoft",
    vllm: "OpenAI"
  };

  const addProviderDialogOpen = writable(false);
  const table = Table.createWithResource(completionModels);

  function handleAddModel(provider: string) {
    alert(
      `To add a model for ${provider}:\n\n` +
        `1. Models are configured in the backend database\n` +
        `2. Contact your system administrator\n` +
        `3. Models will appear here once configured with org="${provider}"`
    );
  }

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
        return createRender(ModelActions, { model: item.value, type: "completionModel" });
      }
    })
  ]);

  function createOrgFilter(org: string | null | undefined) {
    return function (model: CompletionModel) {
      return model.org === org;
    };
  }

  function listAllProviders(
    models: CompletionModel[],
    creds: typeof credentials,
    enabled: boolean
  ): string[] {
    const providersSet = new Set<string>();

    // Add providers from models (these already have proper ModelOrg enum values)
    for (const model of models) {
      if (model.org) providersSet.add(model.org);
    }

    // If tenant credentials enabled, also add providers from credentials (normalize to ModelOrg enum values)
    if (enabled && creds) {
      for (const cred of creds) {
        const normalizedProvider = PROVIDER_ID_TO_ORG[cred.provider.toLowerCase()] || cred.provider;
        providersSet.add(normalizedProvider);
      }
    }

    return Array.from(providersSet);
  }

  function hasModelsForProvider(provider: string): boolean {
    return completionModels.some((m) => m.org?.toLowerCase() === provider.toLowerCase());
  }

  function getCredentialForProvider(provider: string) {
    if (!credentials) return undefined;
    // Case-insensitive provider matching
    const cred = credentials.find((c) => c.provider.toLowerCase() === provider.toLowerCase());
    if (!cred) return undefined;
    return {
      masked_key: cred.masked_key,
      config: cred.config
    };
  }

  $: allProviders = listAllProviders(completionModels, credentials, tenantCredentialsEnabled);
  $: table.update(completionModels);
</script>

<div>
  <Table.Root {viewModel} resourceName={m.resource_models()} displayAs="list">
    {#each allProviders as provider (provider)}
      <Table.Group
        filterFn={createOrgFilter(provider)}
        title={provider}
        forceShow={!hasModelsForProvider(provider)}
      >
        <svelte:fragment slot="title-suffix">
          {#if browser && tenantCredentialsEnabled}
            <div class="flex items-center gap-2">
              <ProviderCredentialIcon {provider} credential={getCredentialForProvider(provider)} />
              <Button
                variant="outlined"
                padding="icon-leading"
                size="sm"
                on:click={() => handleAddModel(provider)}
              >
                <IconPlus />
                Add Model
              </Button>
            </div>
          {/if}
        </svelte:fragment>
      </Table.Group>
    {/each}
  </Table.Root>

  {#if browser && tenantCredentialsEnabled}
    <div class="mt-4 flex justify-start">
      <Button
        variant="outlined"
        padding="icon-leading"
        on:click={() => addProviderDialogOpen.set(true)}
      >
        <IconPlus />
        Add Provider Credentials
      </Button>
    </div>

    <AddProviderDialog openController={addProviderDialogOpen} existingProviders={allProviders} />
  {/if}
</div>
