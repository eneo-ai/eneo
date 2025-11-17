<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { TranscriptionModel } from "@intric/intric-js";
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

  export let transcriptionModels: TranscriptionModel[];
  export let credentials:
    | {
        provider: string;
        masked_key: string;
        config: Record<string, any>;
      }[]
    | undefined = undefined;
  export let tenantCredentialsEnabled: boolean = false;
  const table = Table.createWithResource(transcriptionModels);

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
        return createRender(ModelEnableSwitch, { model: item.value, type: "transcriptionModel" });
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
        return createRender(ModelActions, { model: item.value, type: "transcriptionModel" });
      }
    })
  ]);

  function createOrgFilter(org: string | undefined | null) {
    return function (model: TranscriptionModel) {
      return model.org === org;
    };
  }

  function listOrgs(models: TranscriptionModel[]): string[] {
    const uniqueOrgs = new Set<string>();
    for (const model of models) {
      if (model.org) uniqueOrgs.add(model.org);
    }
    return Array.from(uniqueOrgs);
  }

  /**
   * Get the credential provider ID for a given org.
   * Uses the credential_provider field from the backend (authoritative source).
   */
  function getProviderIdForOrg(org: string): string | undefined {
    const model = transcriptionModels.find((m) => m.org === org);
    return model?.credential_provider;
  }

  function getCredentialForProvider(provider: string) {
    if (!credentials) return undefined;

    const providerId = getProviderIdForOrg(provider);
    if (!providerId) return undefined;

    const cred = credentials.find((c) => c.provider.toLowerCase() === providerId.toLowerCase());
    if (!cred) return undefined;
    return {
      masked_key: cred.masked_key,
      config: cred.config
    };
  }

  $: uniqueOrgs = listOrgs(transcriptionModels);
  $: table.update(transcriptionModels);
</script>

<Table.Root {viewModel} resourceName={m.resource_models()} displayAs="list">
  {#each uniqueOrgs as provider (provider)}
    {@const providerId = getProviderIdForOrg(provider)}
    <Table.Group filterFn={createOrgFilter(provider)} title={provider}>
      <svelte:fragment slot="title-suffix">
        {#if browser && tenantCredentialsEnabled && providerId}
          <ProviderCredentialIcon
            provider={providerId}
            displayName={provider}
            credential={getCredentialForProvider(provider)}
          />
        {/if}
      </svelte:fragment>
    </Table.Group>
  {/each}
</Table.Root>
