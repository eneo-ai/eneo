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
  import TranscriptionServicesTable from "./TranscriptionServicesTable.svelte";
  import ImageModelsTable from "./ImageModelsTable.svelte";
  import MigrationHistoryPanel from "./MigrationHistoryPanel.svelte";
  import { m } from "$lib/paraglide/messages";

  export let data;

  setSecurityContext(data.securityClassifications);
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.models()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.models()} tour="admin-models" />
    <Page.Tabbar>
      <Page.TabTrigger tab="completion_models">{m.completion_models()}</Page.TabTrigger>
      <Page.TabTrigger tab="embedding_models">{m.embedding_models()}</Page.TabTrigger>
      <Page.TabTrigger tab="transcription_models">{m.transcription_models()}</Page.TabTrigger>
      <Page.TabTrigger tab="image_models">{m.image_models()}</Page.TabTrigger>
      <Page.TabTrigger tab="migration_history">{m.migration_history_title()}</Page.TabTrigger>
    </Page.Tabbar>
  </Page.Header>
  <Page.Main>
    <Page.Tab id="completion_models">
      <CompletionModelsTable
        completionModels={data.models.completionModels}
        providers={data.providers}
        favoriteProviders={data.favoriteProviders}
      />
    </Page.Tab>
    <Page.Tab id="embedding_models">
      <EmbeddingModelsTable
        embeddingModels={data.models.embeddingModels}
        providers={data.providers}
        favoriteProviders={data.favoriteProviders}
      />
    </Page.Tab>
    <Page.Tab id="transcription_models">
      <!-- Two sections: models write the text, services label who speaks. -->
      <section aria-labelledby="transcription-models-heading">
        <header class="px-4 pt-4">
          <h2
            id="transcription-models-heading"
            class="text-primary text-sm font-semibold tracking-tight"
          >
            {m.transcription_models_section_title()}
          </h2>
          <p class="text-secondary mt-1 max-w-3xl text-[0.8125rem] leading-relaxed">
            {m.transcription_models_section_description()}
          </p>
        </header>
        <TranscriptionModelsTable
          transcriptionModels={data.models.transcriptionModels}
          providers={data.providers}
          favoriteProviders={data.favoriteProviders}
        />
      </section>
      <TranscriptionServicesTable
        services={data.transcriptionServices}
        classifications={data.securityClassifications.security_classifications}
      />
    </Page.Tab>
    <Page.Tab id="image_models">
      <ImageModelsTable
        imageModels={data.models.imageModels}
        providers={data.providers}
        favoriteProviders={data.favoriteProviders}
      />
    </Page.Tab>
    <Page.Tab id="migration_history">
      <MigrationHistoryPanel />
    </Page.Tab>
  </Page.Main>
</Page.Root>
