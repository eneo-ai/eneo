<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Page } from "$lib/components/layout/index.js";
  import { setSecurityContext } from "$lib/features/security-classifications/SecurityContext.js";
  import CompletionModelsTable from "./CompletionModelsTable.svelte";
  import EmbeddingModelsTable from "./EmbeddingModelsTable.svelte";
  import TranscriptionModelsTable from "./TranscriptionModelsTable.svelte";
  import { m } from "$lib/paraglide/messages";
  import { Button } from "@intric/ui";
  import { Plus } from "lucide-svelte";
  import { writable } from "svelte/store";
  import AddCompletionModelDialog from "./AddCompletionModelDialog.svelte";
  import AddProviderDialog from "./AddProviderDialog.svelte";

  export let data;

  setSecurityContext(data.securityClassifications);

  // Debug logging
  console.log('Page component data:', data);
  console.log('data.tenantModelsEnabled:', data.tenantModelsEnabled);
  console.log('Type of tenantModelsEnabled:', typeof data.tenantModelsEnabled);

  let addModelDialogOpen = writable(false);
  let addProviderDialogOpen = writable(false);
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.models()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.models()} />
    {#if data.tenantModelsEnabled}
      <div class="flex gap-2 ml-auto">
        <Button variant="outlined" on:click={() => addProviderDialogOpen.set(true)}>
          <Plus class="w-4 h-4 mr-2" />
          Add Provider
        </Button>
        <Button variant="primary" on:click={() => addModelDialogOpen.set(true)}>
          <Plus class="w-4 h-4 mr-2" />
          Add Model
        </Button>
      </div>
    {/if}
    <Page.Tabbar>
      <Page.TabTrigger tab="completion_models">{m.completion_models()}</Page.TabTrigger>
      <Page.TabTrigger tab="embedding_models">{m.embedding_models()}</Page.TabTrigger>
      <Page.TabTrigger tab="transcription_models">{m.transcription_models()}</Page.TabTrigger>
    </Page.Tabbar>
  </Page.Header>
  <Page.Main>
    <Page.Tab id="completion_models">
      <CompletionModelsTable
        completionModels={data.models.completionModels}
        providers={data.providers}
        credentials={data.credentials}
        tenantCredentialsEnabled={data.tenantCredentialsEnabled}
        tenantModelsEnabled={data.tenantModelsEnabled}
      />
    </Page.Tab>
    <Page.Tab id="embedding_models">
      <EmbeddingModelsTable
        embeddingModels={data.models.embeddingModels}
        providers={data.providers}
        credentials={data.credentials}
        tenantCredentialsEnabled={data.tenantCredentialsEnabled}
      />
    </Page.Tab>
    <Page.Tab id="transcription_models">
      <TranscriptionModelsTable
        transcriptionModels={data.models.transcriptionModels}
        providers={data.providers}
        credentials={data.credentials}
        tenantCredentialsEnabled={data.tenantCredentialsEnabled}
      />
    </Page.Tab>
  </Page.Main>
</Page.Root>

{#if data.tenantModelsEnabled}
  <AddCompletionModelDialog openController={addModelDialogOpen} providers={data.providers} />
  <AddProviderDialog openController={addProviderDialogOpen} />
{/if}
