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
  import { writable } from "svelte/store";
  import AddCompletionModelDialog from "./AddCompletionModelDialog.svelte";
  import AddEmbeddingModelDialog from "./AddEmbeddingModelDialog.svelte";
  import AddTranscriptionModelDialog from "./AddTranscriptionModelDialog.svelte";

  export let data;

  setSecurityContext(data.securityClassifications);

  let addCompletionModelDialogOpen = writable(false);
  let addEmbeddingModelDialogOpen = writable(false);
  let addTranscriptionModelDialogOpen = writable(false);

  // Track which provider to preselect when opening add model dialogs
  let preSelectedCompletionProviderId = writable<string | null>(null);
  let preSelectedEmbeddingProviderId = writable<string | null>(null);
  let preSelectedTranscriptionProviderId = writable<string | null>(null);
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.models()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.models()} />
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
        addModelDialogOpen={addCompletionModelDialogOpen}
        preSelectedProviderId={preSelectedCompletionProviderId}
      />
    </Page.Tab>
    <Page.Tab id="embedding_models">
      <EmbeddingModelsTable
        embeddingModels={data.models.embeddingModels}
        providers={data.providers}
        addModelDialogOpen={addEmbeddingModelDialogOpen}
        preSelectedProviderId={preSelectedEmbeddingProviderId}
      />
    </Page.Tab>
    <Page.Tab id="transcription_models">
      <TranscriptionModelsTable
        transcriptionModels={data.models.transcriptionModels}
        providers={data.providers}
        addModelDialogOpen={addTranscriptionModelDialogOpen}
        preSelectedProviderId={preSelectedTranscriptionProviderId}
      />
    </Page.Tab>
  </Page.Main>
</Page.Root>

<AddCompletionModelDialog openController={addCompletionModelDialogOpen} providers={data.providers} preSelectedProviderId={preSelectedCompletionProviderId} />
<AddEmbeddingModelDialog openController={addEmbeddingModelDialogOpen} providers={data.providers} preSelectedProviderId={preSelectedEmbeddingProviderId} />
<AddTranscriptionModelDialog openController={addTranscriptionModelDialogOpen} providers={data.providers} preSelectedProviderId={preSelectedTranscriptionProviderId} />
